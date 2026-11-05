import { appendFileSync } from "node:fs";
import { homeSchedule, scheduledBackup } from "../src/schedule.ts";
const deferred = scheduledBackup(Date.now(), true);
const message = deferred
  ? `배포 보류: ${homeSchedule.timeZone} ${homeSchedule.start}–${homeSchedule.end} 종료 구간과 ${homeSchedule.deploySafetyMinutes}분 안전 여유에는 홈·Cloud Run 모두 배포하지 않습니다. 종료 후 홈 readiness를 확인하고 수동 재실행하세요.`
  : "배포 가능 시간입니다. 홈 readiness 및 main CI 확인은 별도로 필요합니다.";
if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, `deferred=${deferred}\n`);
if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${message}\n`);
process.stdout.write(`${message}\n`);
