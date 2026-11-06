import { z } from "zod";
import { getConfig, homeHeaders } from "../src/config.ts";
import { mkdir, writeFile } from "node:fs/promises";
import { createHash, timingSafeEqual } from "node:crypto";

type Report = {
  checkedAt: string;
  credentialIdPresent: boolean;
  credentialSecretPresent: boolean;
  expectedCredentialChecksumPresent: boolean;
  credentialsMatchExpected: boolean | null;
} & (
  | { stage: "configuration" | "request"; networkCode: string | null; ok: false }
  | { stage: "response"; status: number; ok: boolean; cloudflareChallenge: boolean; cloudflareErrorCode: number | null }
);
const checkedAt = new Date().toISOString();
const credentialMetadata: {
  checkedAt: string;
  credentialIdPresent: boolean;
  credentialSecretPresent: boolean;
  expectedCredentialChecksumPresent: boolean;
  credentialsMatchExpected: boolean | null;
} = {
  checkedAt,
  credentialIdPresent: Boolean(process.env.HOME_ACCESS_CLIENT_ID),
  credentialSecretPresent: Boolean(process.env.HOME_ACCESS_CLIENT_SECRET),
  expectedCredentialChecksumPresent: Boolean(process.env.HOME_ACCESS_CREDENTIALS_SHA256),
  credentialsMatchExpected: null
};
let report: Report = { ...credentialMetadata, stage: "configuration", networkCode: null, ok: false };
try {
  const bindings = z.object({ PUBLIC_ORIGIN: z.string(), HOME_ORIGIN: z.string(), BACKUP_ENABLED: z.string().default("false"), BACKUP_ORIGIN: z.string().default(""), HOME_ACCESS_CLIENT_ID: z.string(), HOME_ACCESS_CLIENT_SECRET: z.string() }).parse(process.env);
  const config = getConfig(bindings);
  if (process.env.HOME_ACCESS_CREDENTIALS_SHA256) {
    const expected = z.string().regex(/^[a-f0-9]{64}$/).parse(process.env.HOME_ACCESS_CREDENTIALS_SHA256);
    const actual = createHash("sha256").update(`${bindings.HOME_ACCESS_CLIENT_ID}\n${bindings.HOME_ACCESS_CLIENT_SECRET}`).digest();
    credentialMetadata.credentialsMatchExpected = timingSafeEqual(actual, Buffer.from(expected, "hex"));
    report.credentialsMatchExpected = credentialMetadata.credentialsMatchExpected;
    if (!credentialMetadata.credentialsMatchExpected) throw new Error("Credential comparison failed");
  }
  report.stage = "request";
  const headers = homeHeaders(bindings);
  headers.set("Accept", "application/json");
  headers.set("User-Agent", "ziper-deployment-verification");
  const response = await fetch(`${config.homeOrigin}/readyz`, {
    headers,
    redirect: "manual", signal: AbortSignal.timeout(5_000), cache: "no-store"
  });
  report = { ...credentialMetadata, stage: "response", status: response.status, ok: response.status === 200,
    cloudflareChallenge: response.headers.get("cf-mitigated") === "challenge", cloudflareErrorCode: null };
  console.info(`Home origin readiness HTTP status: ${response.status}`);
  if (response.status !== 200 && response.body) {
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (size < 4096) {
        const chunk = await reader.read();
        if (chunk.done) break;
        const value: unknown = chunk.value;
        if (!(value instanceof Uint8Array)) throw new Error("Invalid response stream");
        const bytes = value.subarray(0, 4096 - size);
        chunks.push(bytes);
        size += bytes.byteLength;
      }
    } finally {
      await reader.cancel();
    }
    const prefix = Buffer.concat(chunks).toString("utf8");
    const code = /(?:error code:\s*|class=["']cf-error-code["']>\s*)(1010|1015|1016|1020|1033|1101|1102)\b/i.exec(prefix)?.[1];
    report.cloudflareErrorCode = code ? Number(code) : null;
  } else {
    await response.body?.cancel();
  }
  if (response.status !== 200) throw new Error("Not ready");
  console.info("Home origin readiness: HTTP 200. No response body or credentials recorded.");
} catch (error: unknown) {
  if (error instanceof Error && error.cause && typeof error.cause === "object" && "code" in error.cause) {
    const code: unknown = error.cause.code;
    if (report.stage === "request" && typeof code === "string" && /^[A-Z0-9_]{1,64}$/.test(code)) report.networkCode = code;
  }
  console.error("Home origin readiness failed; deployment blocked.");
  process.exitCode = 1;
} finally {
  await mkdir("dist", { recursive: true });
  await writeFile("dist/home-origin-health.json", JSON.stringify(report, null, 2));
  console.info(JSON.stringify(report));
}
