import { scheduledBackup, homeSchedule } from "./schedule";
import { DurableObject } from "cloudflare:workers";
import { beginProbe, checkFreshness, completeProbe, initialState, POLICY, stateSchema } from "./policy";
import type { CircuitState } from "./policy";
import { getConfig, homeHeaders } from "./config";
import { mintCloudRunToken } from "./cloud-run";

type Decision = { target: "home" } | { target: "backup"; token: string } | { target: "unavailable" };

export class HomeCircuit extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    void ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS circuit (id INTEGER PRIMARY KEY CHECK (id=1), state TEXT NOT NULL)");
      ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS identity_token (id INTEGER PRIMARY KEY CHECK (id=1), audience TEXT NOT NULL, token TEXT NOT NULL, expires_at INTEGER NOT NULL)");
      ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS identity_refresh (id INTEGER PRIMARY KEY CHECK (id=1), owner TEXT NOT NULL, lease_until INTEGER NOT NULL)");
      ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS transitions (at INTEGER NOT NULL, previous TEXT NOT NULL, next TEXT NOT NULL, generation INTEGER NOT NULL)");
      ctx.storage.sql.exec("INSERT OR IGNORE INTO circuit VALUES (1, ?)", JSON.stringify(initialState(Date.now())));
      if (await ctx.storage.getAlarm() === null) await ctx.storage.setAlarm((Math.floor(Date.now() / POLICY.intervalMs) + 1) * POLICY.intervalMs);
    });
  }

  private load(): CircuitState {
    const row = this.ctx.storage.sql.exec<{ state: string }>("SELECT state FROM circuit WHERE id=1").one();
    return stateSchema.parse(JSON.parse(row.state));
  }

  private save(previous: CircuitState, next: CircuitState): void {
    this.ctx.storage.sql.exec("UPDATE circuit SET state=? WHERE id=1", JSON.stringify(next));
    if (previous.mode.kind !== next.mode.kind) {
      this.ctx.storage.sql.exec("INSERT INTO transitions VALUES (?, ?, ?, ?)", Date.now(), previous.mode.kind, next.mode.kind, next.generation);
      this.ctx.storage.sql.exec("DELETE FROM transitions WHERE rowid NOT IN (SELECT rowid FROM transitions ORDER BY rowid DESC LIMIT 100)");
      console.info(JSON.stringify({ event: "circuit_transition", from: previous.mode.kind, to: next.mode.kind, generation: next.generation }));
    }
  }

  async decide(): Promise<Decision> {
    const mode = this.ctx.storage.transactionSync(() => {
      const previous = this.load();
      const next = checkFreshness(previous, Date.now());
      if (previous !== next) this.save(previous, next);
      return next.mode.kind;
    });
    if (mode === "CLOSED" && !(this.env.SCHEDULE_ENABLED === "true" && scheduledBackup(Date.now()))) return { target: "home" };
    const { backupOrigin } = getConfig(this.env);
    if (!backupOrigin) return { target: "unavailable" };
    const refresh = this.ctx.storage.transactionSync(() => {
      const cached = this.ctx.storage.sql.exec<{ token: string; expires_at: number }>(
        "SELECT token, expires_at FROM identity_token WHERE id=1 AND audience=?", backupOrigin
      ).toArray()[0];
      if (cached && cached.expires_at > Date.now() + 60_000) return { kind: "cached", token: cached.token } satisfies { kind: "cached"; token: string };
      const lease = this.ctx.storage.sql.exec<{ lease_until: number }>("SELECT lease_until FROM identity_refresh WHERE id=1").toArray()[0];
      if (lease && lease.lease_until > Date.now()) return { kind: "waiting" } satisfies { kind: "waiting" };
      const owner = crypto.randomUUID();
      this.ctx.storage.sql.exec("INSERT OR REPLACE INTO identity_refresh VALUES (1, ?, ?)", owner, Date.now() + 10_000);
      return { kind: "refresh", owner } satisfies { kind: "refresh"; owner: string };
    });
    if (refresh.kind === "cached") return { target: "backup", token: refresh.token };
    if (refresh.kind === "waiting") return { target: "unavailable" };
    try {
      const identity = await mintCloudRunToken(this.env.CLOUD_RUN_SERVICE_ACCOUNT_JSON, backupOrigin, Date.now());
      this.ctx.storage.sql.exec("INSERT OR REPLACE INTO identity_token VALUES (1, ?, ?, ?)", backupOrigin, identity.token, identity.expiresAt);
      return { target: "backup", token: identity.token };
    } catch {
      console.error(JSON.stringify({ event: "backup_auth_unavailable" }));
      return { target: "unavailable" };
    } finally {
      this.ctx.storage.sql.exec("DELETE FROM identity_refresh WHERE id=1 AND owner=?", refresh.owner);
    }
  }

  async snapshot() {
    const state = this.load();
    const routing = checkFreshness(state, Date.now());
    const scheduled = this.env.SCHEDULE_ENABLED === "true" && scheduledBackup(Date.now());
    return { state, observedAt: Date.now(), nextAlarmAt: await this.ctx.storage.getAlarm(), schedule: homeSchedule,
      reason: scheduled ? "scheduled_backup" : routing.mode.kind === "CLOSED" ? "home" : "circuit_backup",
      transitions: this.ctx.storage.sql.exec<{ at: number; previous: string; next: string; generation: number }>("SELECT at, previous, next, generation FROM transitions ORDER BY rowid DESC LIMIT 100").toArray() };
  }

  async alarm(): Promise<void> {
    const now = Date.now();
    // Schedule first so origin failure or a crash cannot permanently stop the loop.
    await this.ctx.storage.setAlarm((Math.floor(now / POLICY.intervalMs) + 1) * POLICY.intervalMs);
    const probe = this.ctx.storage.transactionSync(() => {
      const previous = this.load();
      const begun = beginProbe(previous, now);
      if (begun.probe) this.save(previous, begun.state);
      return begun.probe;
    });
    if (!probe) return;
    let healthy = false;
    try {
      const { homeOrigin } = getConfig(this.env);
      const response = await fetch(`${homeOrigin}/readyz`, {
        method: "GET", redirect: "manual", headers: homeHeaders(this.env),
        signal: AbortSignal.timeout(POLICY.probeTimeoutMs), cache: "no-store"
      });
      // Probe bodies are never needed or logged; readiness status is the origin contract.
      healthy = response.status === 200;
      await response.body?.cancel();
    } catch {
      // Network/configuration failure is a failed health observation, not a business error.
      healthy = false;
    }
    this.ctx.storage.transactionSync(() => {
      const previous = this.load();
      const next = completeProbe(previous, probe, healthy, Date.now());
      if (previous !== next) this.save(previous, next);
    });
  }
}
