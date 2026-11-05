import { generateKeyPairSync } from "node:crypto";
import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

// Ephemeral fixture generated locally. Never a real Google service account key.
const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
export default defineConfig({
  plugins: [cloudflareTest({
    remoteBindings: false,
    wrangler: { configPath: "./wrangler.jsonc" },
    miniflare: { bindings: {
      PUBLIC_ORIGIN: "https://api.example.test",
      HOME_ORIGIN: "https://home.example.test",
      BACKUP_ENABLED: "true", BACKUP_ORIGIN: "https://backup.run.app",
      HOME_ACCESS_CLIENT_ID: "test-client", HOME_ACCESS_CLIENT_SECRET: "test-secret",
      CLOUD_RUN_SERVICE_ACCOUNT_JSON: JSON.stringify({
        client_email: "test@test-project.iam.gserviceaccount.com",
        private_key: privateKey.export({ type: "pkcs8", format: "pem" })
      })
    } }
  })],
  test: { include: ["test/backup.test.ts"], fileParallelism: false }
});
