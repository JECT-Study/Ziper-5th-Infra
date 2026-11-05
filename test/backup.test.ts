import { env, exports } from "cloudflare:workers";
import { reset, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initialState } from "../src/policy";
import { z } from "zod";

const outbound = vi.fn<typeof fetch>();
const circuit = () => env.HOME_CIRCUIT.getByName("ziper-home-v1");
beforeEach(() => {
  outbound.mockReset().mockImplementation(() => { throw new Error("Unexpected outbound request"); });
  vi.stubGlobal("fetch", outbound);
});
afterEach(async () => { vi.unstubAllGlobals(); await reset(); });

async function open(): Promise<void> {
  await runInDurableObject(circuit(), async (_instance, ctx) => {
    const state = { ...initialState(Date.now()), mode: { kind: "OPEN", retryAt: Date.now() + 120_000 } };
    ctx.storage.sql.exec("UPDATE circuit SET state=? WHERE id=1", JSON.stringify(state));
    await ctx.storage.setAlarm(Date.now() + 60_000);
  });
}

function googleReply(audience = "https://backup.run.app"): Response {
  const claims = btoa(JSON.stringify({ aud: audience, exp: Math.floor(Date.now() / 1000) + 3600 }));
  // Fake Google response at the network boundary; not a token accepted by Google IAM.
  return Response.json({ id_token: `fixture.${claims}.fixture` });
}

describe("Cloud Run forwarding with mocked external network", () => {
  it("OPEN에서_사용자JWT를보존하고_백업에한번만전달한다", async () => {
    await open();
    outbound.mockImplementationOnce(async (input, init) => {
      const request = new Request(input, init);
      expect(request.url).toBe("https://oauth2.googleapis.com/token");
      const form = new URLSearchParams(new TextDecoder().decode(await request.arrayBuffer()));
      expect(form.get("grant_type")).toBe("urn:ietf:params:oauth:grant-type:jwt-bearer");
      expect(form.get("assertion")?.split(".")).toHaveLength(3);
      const encoded = form.get("assertion")?.split(".")[1];
      if (!encoded) throw new Error("Missing signed assertion");
      const claims = z.object({ aud: z.string(), target_audience: z.string(), iss: z.string() }).parse(JSON.parse(atob(encoded.replaceAll("-", "+").replaceAll("_", "/"))));
      expect(claims.aud).toBe("https://oauth2.googleapis.com/token");
      expect(claims.target_audience).toBe("https://backup.run.app");
      expect(claims.iss).toBe("test@test-project.iam.gserviceaccount.com");
      return googleReply();
    });
    outbound.mockImplementationOnce(async input => {
      const request = new Request(input);
      expect(request.url).toBe("https://backup.run.app/items");
      expect(request.method).toBe("POST");
      expect(await request.text()).toBe("write");
      expect(request.headers.get("Authorization")).toBe("Bearer user-jwt");
      expect(request.headers.get("X-Serverless-Authorization")).toMatch(/^Bearer fixture\./);
      expect(request.headers.get("CF-Access-Client-Secret")).toBeNull();
      return new Response("created", { status: 201 });
    });
    const response = await exports.default.fetch("https://api.example.test/items", { method: "POST", body: "write", headers: { Authorization: "Bearer user-jwt" } });
    expect(response.status).toBe(201);
    expect(await response.text()).toBe("created");
    expect(outbound).toHaveBeenCalledTimes(2);
    // A subsequent admission reuses the persistent identity cache.
    expect((await circuit().decide()).target).toBe("backup");
    expect(outbound).toHaveBeenCalledTimes(2);
  });

  it("Google인증이실패하면_홈으로우회하거나쓰기를재시도하지않고_503을반환한다", async () => {
    await open();
    outbound.mockImplementationOnce(() => Promise.resolve(new Response("private token error", { status: 403 })));
    const response = await exports.default.fetch("https://api.example.test/items", { method: "POST", body: "write" });
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("private token error");
    expect(outbound).toHaveBeenCalledTimes(1);
  });

  it("Google토큰의audience가틀리면_백업에_전달하지않는다", async () => {
    await open();
    outbound.mockImplementationOnce(() => Promise.resolve(googleReply("https://different.run.app")));
    expect((await exports.default.fetch("https://api.example.test/items")).status).toBe(503);
    expect(outbound).toHaveBeenCalledTimes(1);
  });

  it("백업연결이끊기면_쓰기요청을_다시전달하지않는다", async () => {
    await open();
    outbound.mockImplementationOnce(() => Promise.resolve(googleReply()));
    outbound.mockRejectedValueOnce(new Error("backup connection lost"));
    const response = await exports.default.fetch("https://api.example.test/items", { method: "POST", body: "write" });
    expect(response.status).toBe(503);
    expect(outbound).toHaveBeenCalledTimes(2);
  });

  it("토큰갱신중동시요청은_Google인증을_중복실행하지않는다", async () => {
    await open();
    outbound.mockImplementationOnce(async () => {
      await new Promise(resolve => setTimeout(resolve, 30));
      return googleReply();
    });
    const decisions = await Promise.all(Array.from({ length: 30 }, () => circuit().decide()));
    expect(decisions.some(d => d.target === "unavailable")).toBe(true);
    expect(decisions.some(d => d.target === "backup")).toBe(true);
    expect(outbound).toHaveBeenCalledTimes(1);
    expect((await circuit().decide()).target).toBe("backup");
  });

  it("갱신중재시작으로lease가남아도_만료이후_캐시를다시채운다", async () => {
    await open();
    await runInDurableObject(circuit(), (_instance, ctx) => {
      ctx.storage.sql.exec("INSERT INTO identity_refresh VALUES (1, ?, ?)", "abandoned", Date.now() - 1);
    });
    outbound.mockImplementationOnce(() => Promise.resolve(googleReply()));
    expect((await circuit().decide()).target).toBe("backup");
    expect(outbound).toHaveBeenCalledTimes(1);
    await runInDurableObject(circuit(), (_instance, ctx) => {
      expect(ctx.storage.sql.exec("SELECT * FROM identity_refresh").toArray()).toEqual([]);
    });
  });
});
