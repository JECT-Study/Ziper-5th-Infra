import { env, exports } from "cloudflare:workers";
import { abortAllDurableObjects, reset, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initialState, POLICY, stateSchema } from "../src/policy";
import type { CircuitState } from "../src/policy";

const outbound = vi.fn<typeof fetch>();
beforeEach(() => {
  outbound.mockReset().mockImplementation(() => { throw new Error("Unexpected outbound request"); });
  vi.stubGlobal("fetch", outbound);
});
afterEach(async () => { vi.unstubAllGlobals(); await reset(); });

const circuit = () => env.HOME_CIRCUIT.getByName("ziper-home-v1");
async function seed(value: CircuitState): Promise<void> {
  await runInDurableObject(circuit(), async (_instance, ctx) => {
    ctx.storage.sql.exec("UPDATE circuit SET state=? WHERE id=1", JSON.stringify(value));
    await ctx.storage.setAlarm(Date.now() + 60_000);
  });
}
async function read(): Promise<CircuitState> {
  return runInDurableObject(circuit(), (_instance, ctx) => {
    const row = ctx.storage.sql.exec<{ state: string }>("SELECT state FROM circuit WHERE id=1").one();
    return stateSchema.parse(JSON.parse(row.state));
  });
}

describe("Worker and SQLite Durable Object", () => {
  it("CLOSED에서_본문과사용자JWT를_홈서버에한번만전달한다", async () => {
    await seed(initialState(Date.now()));
    outbound.mockImplementationOnce(async input => {
      const request = new Request(input);
      expect(request.url).toBe("https://home.example.test/items?x=1");
      expect(request.method).toBe("POST");
      expect(await request.text()).toBe("payload");
      expect(request.headers.get("Authorization")).toBe("Bearer user-jwt");
      expect(request.headers.get("CF-Access-Client-Secret")).toBe("test-secret");
      expect(request.headers.get("X-Serverless-Authorization")).toBeNull();
      expect(request.headers.get("X-Forwarded-Host")).toBe("api.example.test");
      return new Response("created", { status: 201 });
    });
    const response = await exports.default.fetch("https://api.example.test/items?x=1", {
      method: "POST", body: "payload", headers: { Authorization: "Bearer user-jwt", "CF-Access-Client-Secret": "attacker", "X-Serverless-Authorization": "attacker" }
    });
    expect(response.status).toBe(201);
    expect(await response.text()).toBe("created");
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(outbound).toHaveBeenCalledTimes(1);
  });

  it("OPEN이나HALFOPEN이면_사용자통신을_홈서버에보내지않는다", async () => {
    for (const mode of [{ kind: "OPEN", retryAt: Date.now() + 120_000 }, { kind: "HALF_OPEN", successes: 1 }] satisfies CircuitState["mode"][]) {
      await seed({ ...initialState(Date.now()), mode });
      const response = await exports.default.fetch("https://api.example.test/items");
      expect(response.status).toBe(503);
      expect(await response.json()).toEqual({ status: "unavailable" });
    }
    expect(outbound).not.toHaveBeenCalled();
  });

  it("네트워크오류시_쓰기를_다른오리진으로재전송하지않는다", async () => {
    await seed(initialState(Date.now()));
    outbound.mockRejectedValueOnce(new Error("private upstream failure"));
    const response = await exports.default.fetch("https://api.example.test/items", { method: "POST", body: "write" });
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("private upstream failure");
    expect(outbound).toHaveBeenCalledTimes(1);
  });

  it("알람이재시도되면_실제SQLite에_한표본만저장한다", async () => {
    await seed(initialState(Date.now()));
    outbound.mockImplementationOnce(() => Promise.resolve(Response.json({ status: "UP" })));
    expect(await runDurableObjectAlarm(circuit())).toBe(true);
    expect(await runDurableObjectAlarm(circuit())).toBe(true);
    expect((await read()).samples).toHaveLength(1);
    expect(outbound).toHaveBeenCalledTimes(1);
    await runInDurableObject(circuit(), async (_instance, ctx) => { expect(await ctx.storage.getAlarm()).not.toBeNull(); });
  });

  it("DO가재시작되면_OPEN상태와_다음알람을복원한다", async () => {
    const state: CircuitState = { ...initialState(Date.now()), mode: { kind: "OPEN", retryAt: Date.now() + 120_000 } };
    await seed(state);
    await abortAllDurableObjects();
    expect(await circuit().decide()).toEqual({ target: "unavailable" });
    expect(await read()).toEqual(state);
    await runInDurableObject(circuit(), async (_instance, ctx) => { expect(await ctx.storage.getAlarm()).not.toBeNull(); });
  });

  it("표본이오래되면_동시요청모두_홈서버우회를차단한다", async () => {
    await seed(initialState(Date.now() - POLICY.staleAfterMs - 1000));
    const responses = await Promise.all(Array.from({ length: 12 }, () => exports.default.fetch("https://api.example.test/items")));
    expect(responses.every(r => r.status === 503)).toBe(true);
    expect((await read()).mode.kind).toBe("OPEN");
    expect((await read()).generation).toBe(1);
    expect(outbound).not.toHaveBeenCalled();
  });

  it("홈서버가리다이렉트하면_헬스체크를_실패로기록한다", async () => {
    await seed(initialState(Date.now()));
    outbound.mockImplementationOnce(() => Promise.resolve(new Response(null, { status: 302, headers: { Location: "https://login.example.test" } })));
    await runDurableObjectAlarm(circuit());
    expect((await read()).samples[0]?.healthy).toBe(false);
  });

  it("외부호스트처럼생긴경로가와도_설정한홈서버만_호출한다", async () => {
    await seed(initialState(Date.now()));
    outbound.mockImplementationOnce(input => {
      expect(new Request(input).url).toBe("https://home.example.test//evil.example/items");
      return Promise.resolve(new Response("safe"));
    });
    const response = await exports.default.fetch("https://api.example.test//evil.example/items");
    expect(await response.text()).toBe("safe");
    expect(outbound).toHaveBeenCalledTimes(1);
  });

  it("동시사용자천명이실패해도_윈도우에는_전용검사한건만쌓인다", async () => {
    await seed(initialState(Date.now()));
    outbound.mockImplementation(() => Promise.resolve(new Response(null, { status: 503 })));
    const responses = await Promise.all(Array.from({ length: 1000 }, () => exports.default.fetch("https://api.example.test/items")));
    expect(responses.every(r => r.status === 503)).toBe(true);
    expect((await read()).samples).toEqual([]);
    expect((await read()).mode.kind).toBe("CLOSED");
    await runDurableObjectAlarm(circuit());
    await runDurableObjectAlarm(circuit());
    expect((await read()).samples).toHaveLength(1);
    expect((await read()).samples[0]?.healthy).toBe(false);
    expect(outbound).toHaveBeenCalledTimes(1001);
  });
});
