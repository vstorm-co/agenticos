import { describe, expect, it } from "vitest";

import { holdsHidden, writtenOut } from "./hidden-characters";

describe("hidden characters", () => {
  it("writes out what draws nothing or reorders, and keeps newlines and tabs", () => {
    expect(writtenOut("a\u202Eb\u200Bc\nd\te")).toBe("a\\u{202E}b\\u{200B}c\nd\te");
  });

  it("finds one anywhere in a JSON value, keys included", () => {
    expect(holdsHidden("plain")).toBe(false);
    expect(writtenOut("tag\u{E0001}")).toBe("tag\\u{E0001}");
    expect(holdsHidden({ config: { notes: ["fine", "Ring\u0001bell"] } })).toBe(true);
    expect(holdsHidden({ ["key\u202E"]: "value" })).toBe(true);
    expect(holdsHidden([1, null, true, { id: "charts" }])).toBe(false);
  });
});
