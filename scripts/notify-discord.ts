import { z } from "zod";
const schema = z.object({
  DISCORD_DEPLOY_WEBHOOK_URL: z.url(),
  DEPLOY_RESULT: z.enum(["success", "failure", "deferred"]),
  DEPLOY_SCOPE: z.enum(["home", "paired"]).default("home"),
  SOURCE_SHA: z.string().regex(/^[a-f0-9]{40}$/),
  GITHUB_SERVER_URL: z.literal("https://github.com"),
  GITHUB_REPOSITORY: z.literal("JECT-Study/Ziper-5th-Server"),
  GITHUB_RUN_ID: z.string().regex(/^\d+$/)
});
try {
  const env = schema.parse(process.env);
  const url = new URL(env.DISCORD_DEPLOY_WEBHOOK_URL);
  if (url.protocol !== "https:" || url.hostname !== "discord.com" || !/^\/api\/webhooks\/\d+\/[^/]+$/.test(url.pathname) || url.username || url.password || url.hash || url.search) throw new Error("Invalid webhook");
  url.searchParams.set("wait", "true");
  const description = env.DEPLOY_RESULT === "deferred"
    ? "예약 종료 구간(03–06시 KST) 및 종료 전 30분 안전 여유에는 홈·Cloud Run 배포를 보류합니다. 홈 준비 후 수동 재실행하세요."
    : env.DEPLOY_RESULT === "success" ? (env.DEPLOY_SCOPE === "paired" ? "홈·Cloud Run 동일 이미지 배포와 readiness 확인 완료" : "홈서버 앱 배포와 공개 readiness 확인 완료 (Cloud Run 전환 검증은 별도)") : "배포 실패: 실행 기록에서 반영·복원 상태를 확인하세요.";
  const response = await fetch(url, { method: "POST", redirect: "manual", signal: AbortSignal.timeout(10_000), headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: `[집어 배포 ${env.DEPLOY_RESULT}] ${description}\ncommit: ${env.SOURCE_SHA}\n${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}`, allowed_mentions: { parse: [] } }) });
  if (!response.ok) { await response.body?.cancel(); throw new Error("Notification rejected"); }
  const message = z.object({ id: z.string(), channel_id: z.literal("1566809692779323402") }).parse(await response.json());
  process.stdout.write(`Discord message confirmed: ${message.id}\n`);
} catch {
  // A timeout may mean the message was delivered. Never replay automatically.
  process.stderr.write("Discord notification failed or delivery is unknown. Deployment must not be retried for this reason.\n");
  process.exitCode = 1;
}
