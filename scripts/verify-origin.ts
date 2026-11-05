import { z } from "zod";
import { getConfig, homeHeaders } from "../src/config.ts";

try {
  const bindings = z.object({ PUBLIC_ORIGIN: z.string(), HOME_ORIGIN: z.string(), BACKUP_ENABLED: z.string().default("false"), BACKUP_ORIGIN: z.string().default(""), HOME_ACCESS_CLIENT_ID: z.string(), HOME_ACCESS_CLIENT_SECRET: z.string() }).parse(process.env);
  const config = getConfig(bindings);
  const response = await fetch(`${config.homeOrigin}/readyz`, {
    headers: homeHeaders(bindings),
    redirect: "manual", signal: AbortSignal.timeout(5_000), cache: "no-store"
  });
  await response.body?.cancel();
  if (response.status !== 200) throw new Error("Not ready");
  console.info("Home origin readiness: HTTP 200. No response body or credentials recorded.");
} catch {
  console.error("Home origin readiness failed; deployment blocked.");
  process.exitCode = 1;
}
