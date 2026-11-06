import { z } from "zod";
import { getConfig, homeHeaders } from "../src/config.ts";
import { mkdir, writeFile } from "node:fs/promises";

type Report = { checkedAt: string } & (
  | { stage: "configuration" | "request"; networkCode: string | null; ok: false }
  | { stage: "response"; status: number; ok: boolean }
);
const checkedAt = new Date().toISOString();
let report: Report = { checkedAt, stage: "configuration", networkCode: null, ok: false };
try {
  const bindings = z.object({ PUBLIC_ORIGIN: z.string(), HOME_ORIGIN: z.string(), BACKUP_ENABLED: z.string().default("false"), BACKUP_ORIGIN: z.string().default(""), HOME_ACCESS_CLIENT_ID: z.string(), HOME_ACCESS_CLIENT_SECRET: z.string() }).parse(process.env);
  const config = getConfig(bindings);
  report.stage = "request";
  const response = await fetch(`${config.homeOrigin}/readyz`, {
    headers: homeHeaders(bindings),
    redirect: "manual", signal: AbortSignal.timeout(5_000), cache: "no-store"
  });
  report = { checkedAt, stage: "response", status: response.status, ok: response.status === 200 };
  console.info(`Home origin readiness HTTP status: ${response.status}`);
  await response.body?.cancel();
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
