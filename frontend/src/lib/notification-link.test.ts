import { describe, expect, it } from "vitest";

import { isInAppPath } from "./notification-link";

describe("isInAppPath", () => {
  it("accepts the path a notification is written with today", () => {
    expect(isInAppPath("/agents/a1?org=2a1b3c4d")).toBe(true);
  });

  it("refuses a row written before the column held a path", () => {
    // Not a regression to fix: nothing migrates those rows, and an absolute
    // destination is still rendered - as the plain anchor it always was.
    expect(isInAppPath("https://app.example.com/agents/a1")).toBe(false);
  });

  it("refuses a destination that is another host wearing a path's clothes", () => {
    expect(isInAppPath("//evil.example/agents")).toBe(false);
    expect(isInAppPath("/\\evil.example/agents")).toBe(false);
    expect(isInAppPath("/\t/evil.example")).toBe(false);
  });

  it("refuses a relative destination, which resolves against wherever the reader stands", () => {
    expect(isInAppPath("agents")).toBe(false);
  });
});
