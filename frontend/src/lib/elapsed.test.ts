import { describe, expect, it } from "vitest";

import { formatElapsed } from "./elapsed";

const t = (key: "elapsedSeconds" | "elapsedMinutes", values: Record<string, number>) =>
  key === "elapsedSeconds"
    ? `${values.seconds}s`
    : `${values.minutes}m${values.seconds ? ` ${values.seconds}s` : ""}`;

describe("formatElapsed", () => {
  it("says seconds under a minute, rounded", () => {
    expect(formatElapsed(12_400, t)).toBe("12s");
  });

  it("never says a turn took no time", () => {
    expect(formatElapsed(300, t)).toBe("1s");
  });

  it("says minutes and the seconds left over", () => {
    expect(formatElapsed(159_000, t)).toBe("2m 39s");
    expect(formatElapsed(120_000, t)).toBe("2m");
  });
});
