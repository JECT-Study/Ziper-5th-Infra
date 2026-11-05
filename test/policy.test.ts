import { describe, expect, it } from "vitest";
import { beginProbe, checkFreshness, completeProbe, initialState, POLICY } from "../src/policy";
import type { CircuitState } from "../src/policy";

function observe(state: CircuitState, minute: number, healthy: boolean): CircuitState {
  const now = minute * POLICY.intervalMs;
  const { state: reserved, probe } = beginProbe(state, now);
  if (!probe) throw new Error("Expected a new minute");
  return completeProbe(reserved, probe, healthy, now);
}

function warmed(): CircuitState {
  let state = initialState(0);
  for (let minute = 1; minute <= 10; minute++) state = observe(state, minute, true);
  return state;
}

describe("home circuit policy", () => {
  it("최소표본전에는_실패가있어도_CLOSED를유지한다", () => {
    let state = initialState(0);
    for (let minute = 1; minute <= 5; minute++) state = observe(state, minute, false);
    expect(state.mode.kind).toBe("CLOSED");
    expect(observe(state, 6, false).mode.kind).toBe("OPEN");
  });

  it("열개표본에서_실패율이정확히60퍼센트면_OPEN으로전환한다", () => {
    let state = warmed();
    for (let minute = 11; minute <= 15; minute++) state = observe(state, minute, false);
    expect(state.mode.kind).toBe("CLOSED");
    expect(observe(state, 16, false).mode.kind).toBe("OPEN");
  });

  it("짧은장애후_실패표본이밀려나면_CLOSED를유지한다", () => {
    let state = warmed();
    for (let minute = 11; minute <= 15; minute++) state = observe(state, minute, false);
    for (let minute = 16; minute <= 25; minute++) state = observe(state, minute, true);
    expect(state.mode.kind).toBe("CLOSED");
    expect(state.samples).toHaveLength(10);
    expect(state.samples.every(s => s.healthy)).toBe(true);
  });

  it("OPEN에서_쿨다운과연속성공을거쳐야_CLOSED로복귀한다", () => {
    let state = initialState(0);
    for (let minute = 1; minute <= 6; minute++) state = observe(state, minute, false);
    state = observe(state, 7, true);
    expect(state.mode.kind).toBe("OPEN");
    state = observe(state, 8, true);
    expect(state.mode).toEqual({ kind: "HALF_OPEN", successes: 1 });
    state = observe(state, 9, true);
    expect(state.mode).toEqual({ kind: "HALF_OPEN", successes: 2 });
    state = observe(state, 10, true);
    expect(state.mode.kind).toBe("CLOSED");
    expect(state.samples).toEqual([]);
    expect(observe(state, 11, true).mode.kind).toBe("CLOSED");
  });

  it("HALFOPEN에서_한번실패하면_쿨다운을다시시작한다", () => {
    let state = initialState(0);
    for (let minute = 1; minute <= 6; minute++) state = observe(state, minute, false);
    state = observe(state, 8, true);
    state = observe(state, 9, false);
    expect(state.mode).toEqual({ kind: "OPEN", retryAt: 11 * POLICY.intervalMs });
    expect(observe(state, 10, true).mode.kind).toBe("OPEN");
  });

  it("동일분의알람이재시도되면_한번만_표본을예약한다", () => {
    const first = beginProbe(initialState(0), 60_000);
    expect(beginProbe(first.state, 60_100).probe).toBeNull();
    if (!first.probe) throw new Error("Missing reservation");
    const complete = completeProbe(first.state, first.probe, true, 60_100);
    expect(completeProbe(complete, first.probe, false, 60_200)).toEqual(complete);
  });

  it("관측이중단되면_표본노화와무관하게_OPEN하고이전결과를무시한다", () => {
    const started = beginProbe(warmed(), 11 * POLICY.intervalMs);
    const stale = checkFreshness(started.state, 13 * POLICY.intervalMs);
    expect(stale.mode.kind).toBe("OPEN");
    if (!started.probe) throw new Error("Missing reservation");
    expect(completeProbe(stale, started.probe, true, 13 * POLICY.intervalMs)).toEqual(stale);
    expect(checkFreshness(stale, 100 * POLICY.intervalMs).mode.kind).toBe("OPEN");
  });

  it("새분의관측이있으면_이전분의늦은응답을_무시한다", () => {
    const first = beginProbe(initialState(0), 60_000);
    const second = beginProbe(first.state, 120_000);
    if (!first.probe || !second.probe) throw new Error("Missing reservation");
    expect(completeProbe(second.state, first.probe, true, 120_100)).toEqual(second.state);
  });

  it("HALFOPEN에서관측이누락되면_성공횟수를_처음부터센다", () => {
    let state = initialState(0);
    for (let minute = 1; minute <= 6; minute++) state = observe(state, minute, false);
    state = observe(state, 8, true);
    state = observe(state, 9, true);
    state = observe(state, 11, true);
    expect(state.mode).toEqual({ kind: "HALF_OPEN", successes: 1 });
    const reserved = beginProbe(state, 12 * POLICY.intervalMs);
    // The reserved minute is lost on restart and never completed.
    expect(observe(reserved.state, 13, true).mode).toEqual({ kind: "HALF_OPEN", successes: 1 });
  });
});
