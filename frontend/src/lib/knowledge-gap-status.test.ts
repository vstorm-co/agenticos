import { describe, expect, it } from "vitest";

import { gapStatus } from "./knowledge-gap-status";

describe("gapStatus", () => {
  it("reads a status a link names, and the open topics for anything else", () => {
    expect(gapStatus("covered")).toBe("covered");
    expect(gapStatus("dismissed")).toBe("dismissed");
    expect(gapStatus(null)).toBe("open");
    expect(gapStatus("everything")).toBe("open");
  });
});
