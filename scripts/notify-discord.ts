import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { z } from "zod";
const schema = z.object({
  DISCORD_DEPLOY_WEBHOOK_URL: z.url(),
  DEPLOY_RESULT: z.enum(["success", "failure", "deferred"]),
  DEPLOY_SCOPE: z.enum(["home", "paired"]).default("home"),
  SOURCE_SHA: z.string().regex(/^[a-f0-9]{40}$/),
  GITHUB_SERVER_URL: z.literal("https://github.com"),
  GITHUB_REPOSITORY: z.literal("JECT-Study/Ziper-5th-Server"),
  GITHUB_RUN_ID: z.string().regex(/^[1-9][0-9]*$/),
  GITHUB_RUN_ATTEMPT: z.string().regex(/^[1-9][0-9]*$/)
});
const messageSchema = z.object({
  id: z.string().regex(/^[1-9][0-9]{0,24}$/),
  channel_id: z.literal("1566809692779323402"),
  content: z.string().max(2000)
});
type Delivery =
  | { state: "not_sent" }
  | { state: "unknown" }
  | { state: "rejected"; httpStatus: number }
  | { state: "posted"; messageId: string }
  | { state: "confirmed"; messageId: string; channelId: string; readAttempts: number };
type Context = Pick<z.infer<typeof schema>, "DEPLOY_RESULT" | "DEPLOY_SCOPE" | "SOURCE_SHA" | "GITHUB_RUN_ID" | "GITHUB_RUN_ATTEMPT">;
let context: Context | undefined;
let delivery: Delivery = { state: "not_sent" };
let phase = "configuration";
let readAttempts = 0;
let readStatus: number | null = null;
function saveReceipt() {
  mkdirSync("dist", { recursive: true });
  writeFileSync("dist/discord-deploy-receipt.json.next", JSON.stringify({
    checkedAt: new Date().toISOString(), ...context, phase, delivery, readAttempts, readStatus
  }, null, 2) + "\n");
  renameSync("dist/discord-deploy-receipt.json.next", "dist/discord-deploy-receipt.json");
}
const pause = () => new Promise<void>((resolve) => setTimeout(resolve, 2000));
try {
  const env = schema.parse(process.env);
  const url = new URL(env.DISCORD_DEPLOY_WEBHOOK_URL);
  if (url.protocol !== "https:" || url.hostname !== "discord.com" || !/^\/api\/webhooks\/\d+\/[^/]+$/.test(url.pathname) || url.username || url.password || url.hash || url.search) throw new Error("Invalid webhook");
  context = { DEPLOY_RESULT: env.DEPLOY_RESULT, DEPLOY_SCOPE: env.DEPLOY_SCOPE,
    SOURCE_SHA: env.SOURCE_SHA, GITHUB_RUN_ID: env.GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT: env.GITHUB_RUN_ATTEMPT };
  const description = env.DEPLOY_RESULT === "deferred"
    ? "예약 종료 구간(03–06시 KST) 및 종료 전 30분 안전 여유에는 홈·Cloud Run 배포를 보류합니다. 홈 준비 후 수동 재실행하세요."
    : env.DEPLOY_RESULT === "success" ? (env.DEPLOY_SCOPE === "paired" ? "홈·Cloud Run 동일 이미지 배포와 readiness 확인 완료" : "홈서버 앱 배포와 공개 readiness 확인 완료 (Cloud Run 전환 검증은 별도)") : "배포 실패: 실행 기록에서 반영·복원 상태를 확인하세요.";
  const content = `[집어 배포 ${env.DEPLOY_RESULT}] ${description}\ncommit: ${env.SOURCE_SHA}\nattempt: ${env.GITHUB_RUN_ATTEMPT}\n${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}/attempts/${env.GITHUB_RUN_ATTEMPT}`;
  url.searchParams.set("wait", "true");
  phase = "post";
  delivery = { state: "unknown" };
  saveReceipt();
  const response = await fetch(url, { method: "POST", redirect: "manual", signal: AbortSignal.timeout(10_000), headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, allowed_mentions: { parse: [] } }) });
  if (!response.ok) {
    delivery = { state: "rejected", httpStatus: response.status };
    await response.body?.cancel();
    throw new Error("Notification rejected");
  }
  phase = "verify_post";
  const message = messageSchema.parse(await response.json());
  delivery = { state: "posted", messageId: message.id };
  saveReceipt();
  if (message.content !== content) throw new Error("Notification content differs");
  const readUrl = new URL(url);
  readUrl.search = "";
  readUrl.pathname += `/messages/${message.id}`;
  phase = "get";
  for (let attempt = 1; attempt <= 3; attempt++) {
    readAttempts = attempt;
    readStatus = null;
    saveReceipt();
    let readResponse: Response;
    try {
      readResponse = await fetch(readUrl, { method: "GET", redirect: "manual", signal: AbortSignal.timeout(10_000) });
    } catch {
      if (attempt === 3) throw new Error("Notification read failed");
      await pause();
      continue;
    }
    readStatus = readResponse.status;
    if (!readResponse.ok) {
      await readResponse.body?.cancel();
      if (attempt < 3 && (readStatus === 429 || readStatus >= 500 && readStatus <= 599)) {
        await pause();
        continue;
      }
      throw new Error("Notification read rejected");
    }
    let storedValue: unknown;
    try {
      storedValue = await readResponse.json();
    } catch (error: unknown) {
      if (attempt < 3 && (error instanceof TypeError || error instanceof DOMException
        && (error.name === "AbortError" || error.name === "TimeoutError"))) {
        await pause();
        continue;
      }
      throw new Error("Notification body read failed");
    }
    const stored = messageSchema.parse(storedValue);
    if (stored.id !== message.id || stored.content !== content) throw new Error("Stored notification differs");
    delivery = { state: "confirmed", messageId: stored.id, channelId: stored.channel_id, readAttempts: attempt };
    phase = "complete";
    break;
  }
  process.stdout.write(`Discord message confirmed: ${message.id}\n`);
} catch {
  // A timeout may mean the message was delivered. Never replay automatically.
  process.stderr.write("Discord notification failed or delivery is unknown. Deployment must not be retried for this reason.\n");
  process.exitCode = 1;
} finally {
  saveReceipt();
}
