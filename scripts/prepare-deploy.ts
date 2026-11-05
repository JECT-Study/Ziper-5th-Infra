import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { getConfig } from "../src/config.ts";
import { z } from "zod";

const envSchema = z.object({
  CLOUDFLARE_ACCOUNT_ID: z.string().regex(/^[a-f0-9]{32}$/),
  CLOUDFLARE_ZONE_NAME: z.string().regex(/^[a-z0-9.-]+$/),
  PUBLIC_ORIGIN: z.string(), HOME_ORIGIN: z.string(),
  BACKUP_ORIGIN: z.string().default(""), BACKUP_ENABLED: z.enum(["true", "false"]).default("false"),
  HOME_ACCESS_CLIENT_ID: z.string().min(1), HOME_ACCESS_CLIENT_SECRET: z.string().min(1),
  CLOUD_RUN_SERVICE_ACCOUNT_JSON: z.string().default(""),
  RUNNER_TEMP: z.string().min(1)
});
const configSchema = z.object({
  name: z.literal("ziper-edge"), main: z.string(), compatibility_date: z.string(),
  compatibility_flags: z.array(z.string()), workers_dev: z.literal(false), preview_urls: z.literal(false),
  observability: z.object({ enabled: z.boolean(), head_sampling_rate: z.number() }),
  durable_objects: z.object({ bindings: z.array(z.object({ name: z.string(), class_name: z.string() })) }),
  migrations: z.array(z.object({ tag: z.string(), new_sqlite_classes: z.array(z.string()) })),
  vars: z.record(z.string(), z.string())
});

try {
  const env = envSchema.parse(process.env);
  const config = getConfig(env);
  const hostname = new URL(config.publicOrigin).hostname;
  if (!hostname.endsWith(`.${env.CLOUDFLARE_ZONE_NAME}`)) throw new Error("Zone mismatch");
  if (config.backupOrigin) {
    z.object({ client_email: z.email(), private_key: z.string().startsWith("-----BEGIN PRIVATE KEY-----") }).parse(JSON.parse(env.CLOUD_RUN_SERVICE_ACCOUNT_JSON));
  }
  const template = configSchema.parse(JSON.parse(await readFile("wrangler.jsonc", "utf8")));
  const directory = resolve(".wrangler/deployment");
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await writeFile(resolve(directory, "wrangler.json"), JSON.stringify({
    ...template, main: resolve(template.main), tsconfig: resolve("tsconfig.json"),
    account_id: env.CLOUDFLARE_ACCOUNT_ID,
    routes: [{ pattern: `${hostname}/*`, zone_name: env.CLOUDFLARE_ZONE_NAME }],
    vars: { PUBLIC_ORIGIN: config.publicOrigin, HOME_ORIGIN: config.homeOrigin, BACKUP_ORIGIN: config.backupOrigin ?? "", BACKUP_ENABLED: env.BACKUP_ENABLED }
  }, null, 2), { mode: 0o600 });
  const secrets: Record<string, string> = {
    HOME_ACCESS_CLIENT_ID: env.HOME_ACCESS_CLIENT_ID,
    HOME_ACCESS_CLIENT_SECRET: env.HOME_ACCESS_CLIENT_SECRET
  };
  if (config.backupOrigin) secrets.CLOUD_RUN_SERVICE_ACCOUNT_JSON = env.CLOUD_RUN_SERVICE_ACCOUNT_JSON;
  await writeFile(resolve(env.RUNNER_TEMP, "ziper-worker-secrets.json"), JSON.stringify(secrets), { mode: 0o600 });
  console.info("Production configuration prepared; secret values omitted.");
} catch {
  console.error("Production configuration is incomplete or invalid; deployment blocked.");
  process.exitCode = 1;
}
