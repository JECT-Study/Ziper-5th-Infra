import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { z } from "zod";

const receiptSchema = z.object({
  SOURCE_SHA: z.string(), GITHUB_RUN_ATTEMPT: z.string(), DEPLOY_RESULT: z.string(),
  phase: z.string(), readAttempts: z.number(), readStatus: z.number().nullable(),
  delivery: z.object({ state: z.string(), messageId: z.string().optional() })
});
const cases = [
  { mode: "success", success: true, gets: 1, state: "confirmed" },
  { mode: "get-transient", success: true, gets: 3, state: "confirmed" },
  { mode: "get-network", success: true, gets: 3, state: "confirmed" },
  { mode: "post-timeout", success: false, gets: 0, state: "unknown" },
  { mode: "post-rejected", success: false, gets: 0, state: "rejected" },
  { mode: "post-content", success: false, gets: 0, state: "posted" },
  { mode: "wrong-channel", success: false, gets: 0, state: "unknown" },
  { mode: "get-auth", success: false, gets: 1, state: "posted" },
  { mode: "get-persistent", success: false, gets: 3, state: "posted" },
  { mode: "get-content", success: false, gets: 1, state: "posted" },
  { mode: "get-id", success: false, gets: 1, state: "posted" }
];
for (const fixture of cases) {
  await test(`Discord ${fixture.mode}: persist a receipt without replaying POST`, () => {
    const directory = mkdtempSync(join(tmpdir(), "ziper-discord-"));
    try {
      const loader = join(directory, "fetch.mjs");
      writeFileSync(loader, `
        import assert from "node:assert/strict";
        import { writeFileSync } from "node:fs";
        const trace = { posts: 0, gets: 0, waits: 0 };
        const realTimeout = globalThis.setTimeout;
        globalThis.setTimeout = (callback, delay, ...args) => {
          assert.equal(delay, 2000); trace.waits++;
          return realTimeout(callback, 0, ...args);
        };
        const mode = process.env.FIXTURE_MODE;
        let content;
        globalThis.fetch = async (url, init) => {
          assert.equal(init.redirect, "manual");
          assert.ok(init.signal instanceof AbortSignal);
          if (init.method === "POST") {
            trace.posts++;
            assert.equal(String(url), process.env.DISCORD_DEPLOY_WEBHOOK_URL + "?wait=true");
            const body = JSON.parse(init.body); content = body.content;
            assert.deepEqual(body.allowed_mentions, { parse: [] });
            assert.ok(content.includes("attempt: 2"));
            assert.ok(content.includes("/actions/runs/123456/attempts/2"));
            if (mode === "post-timeout") throw new Error("fixture-private-response");
            if (mode === "post-rejected") return new Response("fixture-private-response", { status: 503 });
            return Response.json({ id: "987654321", channel_id: mode === "wrong-channel" ? "123" : "1566809692779323402",
              content: mode === "post-content" ? "fixture-private-response" : content });
          }
          assert.equal(init.method, "GET"); trace.gets++;
          assert.equal(String(url), process.env.DISCORD_DEPLOY_WEBHOOK_URL + "/messages/987654321");
          if (mode === "get-network" && trace.gets < 3) throw new Error("fixture-private-response");
          if (mode === "get-transient" && trace.gets < 3) return new Response("fixture-private-response", { status: trace.gets === 1 ? 429 : 503 });
          if (mode === "get-auth") return new Response("fixture-private-response", { status: 403 });
          if (mode === "get-persistent") return new Response("fixture-private-response", { status: 503 });
          return Response.json({ id: mode === "get-id" ? "111111111" : "987654321", channel_id: "1566809692779323402",
            content: mode === "get-content" ? "fixture-private-response" : content });
        };
        process.on("exit", () => writeFileSync("trace.json", JSON.stringify(trace)));
      `);
      const result = spawnSync(process.execPath, ["--import", loader, resolve("scripts/notify-discord.ts")], {
        cwd: directory, encoding: "utf8", timeout: 5000,
        env: { ...process.env, DISCORD_DEPLOY_WEBHOOK_URL: "https://discord.com/api/webhooks/123456/fixture-private-token",
          DEPLOY_RESULT: "success", DEPLOY_SCOPE: "paired", SOURCE_SHA: "a".repeat(40),
          GITHUB_SERVER_URL: "https://github.com", GITHUB_REPOSITORY: "JECT-Study/Ziper-5th-Server",
          GITHUB_RUN_ID: "123456", GITHUB_RUN_ATTEMPT: "2", FIXTURE_MODE: fixture.mode }
      });
      assert.equal(result.status, fixture.success ? 0 : 1, result.stderr);
      const raw = readFileSync(join(directory, "dist/discord-deploy-receipt.json"), "utf8");
      const receipt = receiptSchema.parse(JSON.parse(raw));
      const trace = z.object({ posts: z.number(), gets: z.number(), waits: z.number() })
        .parse(JSON.parse(readFileSync(join(directory, "trace.json"), "utf8")));
      assert.equal(trace.posts, 1);
      assert.equal(trace.gets, fixture.gets);
      assert.equal(trace.waits, Math.max(0, fixture.gets - 1));
      assert.equal(receipt.delivery.state, fixture.state);
      assert.equal(receipt.GITHUB_RUN_ATTEMPT, "2");
      assert.equal(receipt.SOURCE_SHA, "a".repeat(40));
      assert.equal(receipt.readAttempts, fixture.gets);
      assert.equal(receipt.phase === "complete", fixture.success);
      for (const marker of ["fixture-private-token", "fixture-private-response", "/api/webhooks/"]) {
        assert.ok(!(raw + result.stdout + result.stderr).includes(marker));
      }
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
}
