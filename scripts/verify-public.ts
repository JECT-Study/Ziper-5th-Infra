// Public request also initializes the Durable Object and its periodic alarm.
export {};
try {
  const url = new URL(process.env.PUBLIC_ORIGIN ?? "");
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error("Invalid origin");
  for (let sample = 0; sample < 3; sample++) {
    const response = await fetch(new URL("/readyz", url), { redirect: "manual", cache: "no-store", signal: AbortSignal.timeout(10_000) });
    const body: unknown = await response.json();
    if (response.status !== 200 || typeof body !== "object" || body === null || !("status" in body) || body.status !== "UP" || response.headers.get("Cache-Control") !== "no-store") throw new Error("Not ready");
    if (sample < 2) await new Promise(resolve => setTimeout(resolve, 10_000));
  }
  console.info("Public readiness: 3 successful samples. Failover and uptime history are not verified by this check.");
} catch {
  console.error("Public readiness failed after deployment; inspect deployment and circuit state. No automatic replay or route removal performed.");
  process.exitCode = 1;
}
