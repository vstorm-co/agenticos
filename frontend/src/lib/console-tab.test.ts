import { describe, expect, it } from "vitest";

import { CONSOLE_TAB, CONSOLE_TAB_HEADER } from "./console-tab";

describe("console tab", () => {
  it("is one opaque id per loaded tab, sent under a fixed header", () => {
    expect(CONSOLE_TAB).toMatch(/^[A-Za-z0-9-]{1,64}$/);
    expect(CONSOLE_TAB_HEADER).toBe("X-Console-Tab");
  });
});
