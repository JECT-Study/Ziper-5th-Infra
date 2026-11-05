// Secret bindings are supplied by `wrangler secret put` or the production environment.
interface Env {
  HOME_ACCESS_CLIENT_ID: string;
  HOME_ACCESS_CLIENT_SECRET: string;
  CLOUD_RUN_SERVICE_ACCOUNT_JSON: string;
}
