import { getConfig, homeHeaders } from "./config";
import { POLICY } from "./policy";
export { HomeCircuit } from "./circuit";

function unavailable(): Response {
  return Response.json({ status: "unavailable" }, {
    status: 503,
    headers: { "Cache-Control": "no-store", "Retry-After": "60" }
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      const config = getConfig(env);
      const incoming = new URL(request.url);
      if (incoming.origin !== config.publicOrigin) return new Response(null, { status: 404 });
      const decision = await env.HOME_CIRCUIT.getByName("ziper-home-v1").decide();
      if (decision.target === "unavailable") return unavailable();
      const origin = decision.target === "home" ? config.homeOrigin : config.backupOrigin;
      if (!origin) return unavailable();
      const destination = new URL(origin);
      // Assign components to avoid treating a //path as a different upstream host.
      destination.pathname = incoming.pathname;
      destination.search = incoming.search;
      const headers = new Headers(request.headers);
      for (const name of ["Host", "CF-Access-Client-Id", "CF-Access-Client-Secret", "CF-Access-Jwt-Assertion", "X-Serverless-Authorization", "Forwarded", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Forwarded-For"]) headers.delete(name);
      headers.set("X-Forwarded-Host", incoming.host);
      headers.set("X-Forwarded-Proto", "https");
      if (decision.target === "home") homeHeaders(env).forEach((value, name) => headers.set(name, value));
      else headers.set("X-Serverless-Authorization", `Bearer ${decision.token}`);
      const upstream = new Request(destination, request);
      const signal = AbortSignal.any([request.signal, AbortSignal.timeout(POLICY.requestTimeoutMs)]);
      // No cross-origin retry, including GET: a consumed body or uncertain write is never replayed.
      const response = await fetch(new Request(upstream, { headers, redirect: "manual", signal, cache: "no-store" }));
      const result = new Response(response.body, response);
      result.headers.set("Cache-Control", "no-store");
      for (const name of ["CF-Access-Client-Id", "CF-Access-Client-Secret", "CF-Access-Jwt-Assertion", "X-Serverless-Authorization"]) result.headers.delete(name);
      return result;
    } catch {
      console.error(JSON.stringify({ event: "edge_request_unavailable" }));
      return unavailable();
    }
  }
} satisfies ExportedHandler<Env>;
