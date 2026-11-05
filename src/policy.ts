import { z } from "zod";

export const POLICY = Object.freeze({
  intervalMs: 60_000,
  windowSize: 10,
  minimumSamples: 6,
  failurePercent: 60,
  openCooldownMs: 120_000,
  recoverySuccesses: 3,
  staleAfterMs: 120_000,
  probeTimeoutMs: 5_000,
  requestTimeoutMs: 30_000
});

const modeSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("CLOSED") }),
  z.object({ kind: z.literal("OPEN"), retryAt: z.number().int() }),
  z.object({ kind: z.literal("HALF_OPEN"), successes: z.number().int().nonnegative() })
]);
export const stateSchema = z.object({
  version: z.literal(1),
  generation: z.number().int().nonnegative(),
  lastSlot: z.number().int(),
  lastObservedAt: z.number().int(),
  samples: z.array(z.object({ slot: z.number().int(), healthy: z.boolean() })).max(10),
  mode: modeSchema
});
export type CircuitState = z.infer<typeof stateSchema>;
export type Probe = { slot: number; generation: number };

export function initialState(now: number): CircuitState {
  return { version: 1, generation: 0, lastSlot: -1, lastObservedAt: now, samples: [], mode: { kind: "CLOSED" } };
}

function open(state: CircuitState, now: number): CircuitState {
  return { ...state, generation: state.generation + 1, mode: { kind: "OPEN", retryAt: now + POLICY.openCooldownMs } };
}

export function checkFreshness(state: CircuitState, now: number): CircuitState {
  if (state.mode.kind !== "OPEN" && now - state.lastObservedAt > POLICY.staleAfterMs) {
    return open(state, now);
  }
  return state;
}

// Reservation is persisted before external I/O. The same minute cannot earn two votes.
export function beginProbe(state: CircuitState, now: number): { state: CircuitState; probe: Probe | null } {
  const slot = Math.floor(now / POLICY.intervalMs);
  if (slot <= state.lastSlot) return { state, probe: null };
  let next = checkFreshness(state, now);
  if (next.mode.kind === "OPEN" && now >= next.mode.retryAt) {
    next = { ...next, mode: { kind: "HALF_OPEN", successes: 0 } };
  }
  if (next.mode.kind === "HALF_OPEN" && (slot > state.lastSlot + 1 ||
    (state.mode.kind === "HALF_OPEN" && !state.samples.some(s => s.slot === state.lastSlot)))) {
    next = { ...next, mode: { kind: "HALF_OPEN", successes: 0 } };
  }
  next = { ...next, lastSlot: slot };
  return { state: next, probe: { slot, generation: next.generation } };
}

export function completeProbe(state: CircuitState, probe: Probe, healthy: boolean, now: number): CircuitState {
  if (probe.generation !== state.generation || probe.slot !== state.lastSlot || state.samples.some(s => s.slot === probe.slot)) return state;
  const samples = [...state.samples.filter(s => s.slot > probe.slot - POLICY.windowSize), { slot: probe.slot, healthy }];
  const next = { ...state, lastObservedAt: now, samples };
  switch (state.mode.kind) {
    case "CLOSED": {
      const failures = samples.filter(s => !s.healthy).length;
      return samples.length >= POLICY.minimumSamples && failures * 100 >= POLICY.failurePercent * samples.length ? open(next, now) : next;
    }
    case "OPEN":
      return next;
    case "HALF_OPEN": {
      if (!healthy) return open(next, now);
      const successes = state.mode.successes + 1;
      if (successes < POLICY.recoverySuccesses) return { ...next, mode: { kind: "HALF_OPEN", successes } };
      // A new generation must not inherit the failures that caused the previous OPEN.
      return { ...next, generation: next.generation + 1, samples: [], mode: { kind: "CLOSED" } };
    }
    default: {
      const exhaustive: never = state.mode;
      return exhaustive;
    }
  }
}
