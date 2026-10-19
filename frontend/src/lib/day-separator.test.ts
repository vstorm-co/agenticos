import { describe, expect, it } from "vitest";

import { dayLabel, startsADay } from "./day-separator";

const t = (key: "today" | "yesterday") => (key === "today" ? "Today" : "Yesterday");
const NOW = new Date(2026, 9, 13, 15, 0);

describe("dayLabel", () => {
  it("names today and yesterday", () => {
    expect(dayLabel(new Date(2026, 9, 13, 1, 0), NOW, "en", t)).toBe("Today");
    expect(dayLabel(new Date(2026, 9, 12, 23, 0), NOW, "en", t)).toBe("Yesterday");
  });

  it("names an older day by its date, with the year only once it differs", () => {
    expect(dayLabel(new Date(2026, 9, 5), NOW, "en", t)).toBe("Monday, October 5");
    expect(dayLabel(new Date(2025, 11, 31), NOW, "en", t)).toBe("Wednesday, December 31, 2025");
  });
});

describe("startsADay", () => {
  it("is false past the end of the list", () => {
    expect(startsADay([], 0, NOW)).toBe(false);
  });
});
