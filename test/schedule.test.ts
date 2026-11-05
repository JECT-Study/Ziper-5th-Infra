import { describe, it, expect } from "vitest";
import { homeSchedule, scheduledBackup } from "../src/schedule";

describe("KST scheduled routing", () => {
  it.each([
    ["2026-11-05T17:59:59Z", false], ["2026-11-05T18:00:00Z", true],
    ["2026-11-05T20:59:59Z", true], ["2026-11-05T21:00:00Z", false]
  ])("%s routes to backup: %s", (instant, expected) => {
    expect(scheduledBackup(Date.parse(instant))).toBe(expected);
  });
  it("blocks deployment during the safety interval", () => {
    expect(scheduledBackup(Date.parse("2026-11-05T17:30:00Z"), true)).toBe(true);
    expect(scheduledBackup(Date.parse("2026-11-05T17:29:59Z"), true)).toBe(false);
  });
  it("supports changed windows spanning midnight", () => {
    const schedule = { ...homeSchedule, start: "23:00", end: "02:00" };
    expect(scheduledBackup(Date.parse("2026-11-05T15:30:00Z"), false, schedule)).toBe(true);
    expect(scheduledBackup(Date.parse("2026-11-05T17:00:00Z"), false, schedule)).toBe(false);
  });
  it("rejects an ambiguous full-day window", () => {
    expect(() => scheduledBackup(Date.now(), false, { ...homeSchedule, end: "03:00" })).toThrow();
  });
});
