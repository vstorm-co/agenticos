import { describe, expect, it } from "vitest";

import { isSafeReturnPath } from "./safe-return-path";

const ORIGIN = "https://console.example";

describe("isSafeReturnPath", () => {
  it("accepts one of this app's own paths, query and fragment included", () => {
    expect(isSafeReturnPath("/chat?id=abc#top", ORIGIN)).toBe(true);
  });

  it.each([
    ["nothing remembered", null],
    ["nothing at all", undefined],
    ["a scheme", "https://evil.example"],
    ["a protocol-relative path", "//evil.example/x"],
    ["a backslash variant browsers normalise to //", "/\\evil.example"],
    ["a relative path, which resolves against wherever the visitor stands", "agents"],
  ])("refuses %s", (_why, path) => {
    expect(isSafeReturnPath(path, ORIGIN)).toBe(false);
  });

  it.each(["/\t/evil.example", "/\n/evil.example", "/\r/evil.example"])(
    "refuses a control character the URL parser strips before parsing (%j)",
    (path) => {
      // The regex passes this one: it starts with a slash and the next character
      // is neither a slash nor a backslash. Only resolving it says where it goes.
      expect(new URL(path, ORIGIN).origin).toBe("https://evil.example");
      expect(isSafeReturnPath(path, ORIGIN)).toBe(false);
    },
  );
});
