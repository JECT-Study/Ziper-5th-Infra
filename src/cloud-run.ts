import { z } from "zod";

const accountSchema = z.object({
  client_email: z.email().refine(s => s.endsWith(".iam.gserviceaccount.com")),
  private_key: z.string().startsWith("-----BEGIN PRIVATE KEY-----")
});
const tokenSchema = z.object({ id_token: z.string().min(1) });
const claimsSchema = z.object({ exp: z.number().int(), aud: z.string() });
const TOKEN_URL = "https://oauth2.googleapis.com/token";

function base64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export async function mintCloudRunToken(secret: string, audience: string, now: number): Promise<{ token: string; expiresAt: number }> {
  const account = accountSchema.parse(JSON.parse(secret));
  const encode = (value: object) => base64url(new TextEncoder().encode(JSON.stringify(value)));
  const iat = Math.floor(now / 1000);
  const unsigned = `${encode({ alg: "RS256", typ: "JWT" })}.${encode({ iss: account.client_email, aud: TOKEN_URL, iat, exp: iat + 3600, target_audience: audience })}`;
  const keyData = Uint8Array.from(atob(account.private_key.replace(/-----[^-]+-----|\s/g, "")), c => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", keyData, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(unsigned));
  const response = await fetch(TOKEN_URL, {
    method: "POST", redirect: "manual", signal: AbortSignal.timeout(5_000),
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion: `${unsigned}.${base64url(new Uint8Array(signature))}` })
  });
  if (!response.ok) { await response.body?.cancel(); throw new Error("Cloud Run authentication unavailable"); }
  const { id_token: token } = tokenSchema.parse(await response.json());
  const encoded = token.split(".")[1];
  if (!encoded) throw new Error("Invalid identity token");
  const claims = claimsSchema.parse(JSON.parse(atob(encoded.replaceAll("-", "+").replaceAll("_", "/"))));
  if (claims.aud !== audience || claims.exp * 1000 <= now + 60_000) throw new Error("Invalid identity claims");
  return { token, expiresAt: claims.exp * 1000 };
}
