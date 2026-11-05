import { z } from "zod";

function origin(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash || url.port || url.hostname.endsWith(".invalid")) {
    throw new Error("Invalid origin configuration");
  }
  return url.origin;
}

const homeSecrets = z.object({
  HOME_ACCESS_CLIENT_ID: z.string().min(1),
  HOME_ACCESS_CLIENT_SECRET: z.string().min(1)
});

export function getConfig(env: Pick<Env, "PUBLIC_ORIGIN" | "HOME_ORIGIN" | "BACKUP_ORIGIN" | "BACKUP_ENABLED" | "HOME_ACCESS_CLIENT_ID" | "HOME_ACCESS_CLIENT_SECRET">) {
  const publicOrigin = origin(env.PUBLIC_ORIGIN);
  const homeOrigin = origin(env.HOME_ORIGIN);
  if (publicOrigin === homeOrigin) throw new Error("Origin must bypass the Worker route");
  const credentials = homeSecrets.parse(env);
  if (env.BACKUP_ENABLED !== "false" && env.BACKUP_ENABLED !== "true") throw new Error("Invalid backup flag");
  const backupOrigin = env.BACKUP_ENABLED === "true" ? origin(env.BACKUP_ORIGIN) : null;
  if (backupOrigin && (!new URL(backupOrigin).hostname.endsWith(".run.app") || backupOrigin === publicOrigin || backupOrigin === homeOrigin)) {
    throw new Error("Backup must use its Cloud Run service URL");
  }
  return { publicOrigin, homeOrigin, backupOrigin, credentials };
}

export function homeHeaders(env: Parameters<typeof getConfig>[0]): Headers {
  const { credentials } = getConfig(env);
  return new Headers({
    "CF-Access-Client-Id": credentials.HOME_ACCESS_CLIENT_ID,
    "CF-Access-Client-Secret": credentials.HOME_ACCESS_CLIENT_SECRET
  });
}
