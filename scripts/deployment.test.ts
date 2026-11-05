import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { z } from "zod";

const configSchema = z.object({
  vars: z.object({ BACKUP_ENABLED: z.string() }),
  routes: z.array(z.object({ pattern: z.string(), zone_name: z.string() }))
});

await test("배포설정경계_경로와비밀파일을검사하고_잘못된설정을거부한다", () => {
  const directory = mkdtempSync(join(tmpdir(), "ziper-deploy-fixture-"));
  const env = {
    ...process.env, OPS_READ_TOKEN: "fixture".repeat(8), CLOUDFLARE_ACCOUNT_ID: "a".repeat(32), CLOUDFLARE_ZONE_NAME: "example.test",
    PUBLIC_ORIGIN: "https://api.example.test", HOME_ORIGIN: "https://home.example.test",
    BACKUP_ENABLED: "false", BACKUP_ORIGIN: "", HOME_ACCESS_CLIENT_ID: "fixture-id",
    HOME_ACCESS_CLIENT_SECRET: "fixture-secret", RUNNER_TEMP: directory
  };
  try {
    const valid = spawnSync(process.execPath, ["scripts/prepare-deploy.ts"], { env, encoding: "utf8" });
    assert.equal(valid.status, 0);
    assert.ok(!(valid.stdout + valid.stderr).includes("fixture-secret"));
    const raw = readFileSync(".wrangler/deployment/wrangler.json", "utf8");
    const config = configSchema.parse(JSON.parse(raw));
    assert.deepEqual(config.routes, [{ pattern: "api.example.test/*", zone_name: "example.test" }]);
    assert.equal(config.vars.BACKUP_ENABLED, "false");
    assert.ok(!raw.includes("fixture-secret"));
    assert.equal(statSync(join(directory, "ziper-worker-secrets.json")).mode & 0o777, 0o600);
    for (const override of [
      { HOME_ORIGIN: "https://api.example.test" },
      { HOME_ORIGIN: "https://name:password@home.example.test" },
      { HOME_ORIGIN: "https://home-origin.invalid" },
      { HOME_ORIGIN: "https://home.example.test/readyz" },
      { BACKUP_ENABLED: "true" },
      { CLOUDFLARE_ZONE_NAME: "unrelated.test" }
    ]) {
      const invalid = spawnSync(process.execPath, ["scripts/prepare-deploy.ts"], { env: { ...env, ...override }, encoding: "utf8" });
      assert.notEqual(invalid.status, 0);
      assert.ok(!(invalid.stdout + invalid.stderr).includes("password"));
      assert.ok(!(invalid.stdout + invalid.stderr).includes("fixture-secret"));
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
