import { describe, expect, it } from "vitest";

import { clock } from "./clock";

describe("clock", () => {
  it("formats seconds as m:ss, never below zero", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(605)).toBe("10:05");
    expect(clock(59.9)).toBe("0:59");
    expect(clock(-3)).toBe("0:00");
  });
});
