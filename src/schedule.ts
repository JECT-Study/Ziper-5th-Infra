import production from "../config/production.json" with { type: "json" };
import { z } from "zod";

const clock = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/);
const schema = z.object({ timeZone: z.literal("Asia/Seoul"), start: clock, end: clock, deploySafetyMinutes: z.number().int().min(0).max(120) }).refine(s => s.start !== s.end);
export const homeSchedule = schema.parse(production.homeSchedule);
function minutes(value: string): number {
  const [hour, minute] = value.split(":").map(Number);
  if (hour === undefined || minute === undefined) throw new Error("Invalid clock");
  return hour * 60 + minute;
}
export function scheduledBackup(now: number, safety = false, schedule = homeSchedule): boolean {
  const valid = schema.parse(schedule);
  const local = new Intl.DateTimeFormat("en-GB", { timeZone: valid.timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(now));
  const start = (minutes(valid.start) - (safety ? valid.deploySafetyMinutes : 0) + 1440) % 1440;
  const end = minutes(valid.end);
  const current = minutes(local);
  return start < end ? current >= start && current < end : current >= start || current < end;
}
