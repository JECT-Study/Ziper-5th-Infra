import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { z } from "zod";
import { createHash } from "node:crypto";

const configSchema = z.object({
  vars: z.object({ BACKUP_ENABLED: z.string() }),
  routes: z.array(z.object({ pattern: z.string(), zone_name: z.string() }))
});

await test("origin진단_비밀과본문을노출하지않고_검증된차단신호만기록한다", async (t) => {
  const directory = mkdtempSync(join(tmpdir(), "ziper-origin-fixture-"));
  const loader = join(directory, "fetch.mjs");
  const id = "fixture-id";
  const secret = "fixture-private-secret";
  const checksum = createHash("sha256").update(`${id}\n${secret}`).digest("hex");
  const bodyTrap = "fixture-private-response-body";
  writeFileSync(loader, `
    import assert from "node:assert/strict";
    globalThis.fetch = async (url, init) => {
      assert.equal(url, "https://home.example.test/readyz");
      const headers = new Headers(init.headers);
      assert.equal(headers.get("accept"), "application/json");
      assert.equal(headers.get("user-agent"), "ziper-deployment-verification");
      assert.equal(headers.get("CF-Access-Client-Id"), process.env.HOME_ACCESS_CLIENT_ID);
      assert.equal(headers.get("CF-Access-Client-Secret"), process.env.HOME_ACCESS_CLIENT_SECRET);
      assert.equal(init.redirect, "manual");
      assert.equal(init.cache, "no-store");
      return new Response(process.env.FIXTURE_BODY, {
        status: Number(process.env.FIXTURE_STATUS),
        headers: { "cf-mitigated": process.env.FIXTURE_MITIGATED || "" }
      });
    };
  `);
  const schema = z.object({ stage: z.string(), status: z.number().optional(), ok: z.boolean(),
    credentialIdPresent: z.boolean(), credentialSecretPresent: z.boolean(),
    expectedCredentialChecksumPresent: z.boolean(), credentialsMatchExpected: z.boolean().nullable(),
    cloudflareChallenge: z.boolean().optional(), cloudflareErrorCode: z.number().nullable().optional() });
  try {
    for (const fixture of [
      { name: "정상200", status: 200, body: bodyTrap, code: null, challenge: false },
      { name: "Access403_원인코드없음", status: 403, body: bodyTrap, code: null, challenge: false },
      { name: "WAF1020", status: 403, body: `error code: 1020 ${bodyTrap}`, code: 1020, challenge: false },
      { name: "HTML1033", status: 530, body: `<span class="cf-error-code">1033</span>${bodyTrap}`, code: 1033, challenge: false },
      { name: "challenge헤더", status: 403, body: bodyTrap, code: null, challenge: true },
      { name: "임의숫자거부", status: 403, body: `1020 error code: 9999 ${bodyTrap}`, code: null, challenge: false },
      { name: "본문4096바이트제한", status: 403, body: `${"x".repeat(4096)}error code: 1020 ${bodyTrap}`, code: null, challenge: false }
    ]) {
      await t.test(fixture.name, () => {
        const result = spawnSync(process.execPath, ["--import", loader, "scripts/verify-origin.ts"], {
          encoding: "utf8", env: { ...process.env,
            PUBLIC_ORIGIN: "https://api.example.test", HOME_ORIGIN: "https://home.example.test",
            BACKUP_ENABLED: "false", BACKUP_ORIGIN: "", HOME_ACCESS_CLIENT_ID: id, HOME_ACCESS_CLIENT_SECRET: secret,
            HOME_ACCESS_CREDENTIALS_SHA256: checksum, FIXTURE_STATUS: String(fixture.status), FIXTURE_BODY: fixture.body,
            FIXTURE_MITIGATED: fixture.challenge ? "challenge" : "" }
        });
        assert.equal(result.status, fixture.status === 200 ? 0 : 1);
        const report = schema.parse(JSON.parse(readFileSync("dist/home-origin-health.json", "utf8")));
        assert.equal(report.stage, "response");
        assert.equal(report.status, fixture.status);
        assert.equal(report.ok, fixture.status === 200);
        assert.equal(report.credentialsMatchExpected, true);
        assert.equal(report.cloudflareChallenge, fixture.challenge);
        assert.equal(report.cloudflareErrorCode, fixture.code);
        for (const value of [id, secret, checksum, bodyTrap]) {
          assert.ok(!(result.stdout + result.stderr + JSON.stringify(report)).includes(value));
        }
      });
    }
    await t.test("자격불일치면요청전중단", () => {
      const result = spawnSync(process.execPath, ["--import", loader, "scripts/verify-origin.ts"], {
        encoding: "utf8", env: { ...process.env,
          PUBLIC_ORIGIN: "https://api.example.test", HOME_ORIGIN: "https://home.example.test",
          BACKUP_ENABLED: "false", BACKUP_ORIGIN: "", HOME_ACCESS_CLIENT_ID: id, HOME_ACCESS_CLIENT_SECRET: secret,
          HOME_ACCESS_CREDENTIALS_SHA256: "0".repeat(64) }
      });
      const report = schema.parse(JSON.parse(readFileSync("dist/home-origin-health.json", "utf8")));
      assert.equal(result.status, 1);
      assert.equal(report.stage, "configuration");
      assert.equal(report.credentialsMatchExpected, false);
      assert.equal(report.status, undefined);
    });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
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
