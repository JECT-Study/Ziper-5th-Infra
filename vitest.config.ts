import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [cloudflareTest({
    remoteBindings: false,
    wrangler: { configPath: "./wrangler.jsonc" },
    miniflare: { bindings: {
      PUBLIC_ORIGIN: "https://api.example.test",
      HOME_ORIGIN: "https://home.example.test",
      BACKUP_ENABLED: "false",
      BACKUP_ORIGIN: "",
      HOME_ACCESS_CLIENT_ID: "test-client",
      HOME_ACCESS_CLIENT_SECRET: "test-secret"
    } }
  })],
  test: { include: ["test/**/*.test.ts"], fileParallelism: false, exclude: [...configDefaults.exclude, "test/backup.test.ts"] }
});
