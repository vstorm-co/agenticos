import { describe, expect, it } from "vitest";

import { isConsolePath } from "./paths";

describe("isConsolePath", () => {
  it("accepts a path on the console and refuses anything that could leave it", () => {
    expect(isConsolePath("/runs?tab=approvals")).toBe(true);
    expect(isConsolePath("/pl/chat?id=1")).toBe(true);
    expect(isConsolePath("https://evil.example/")).toBe(false);
    expect(isConsolePath("//evil.example/x")).toBe(false);
    expect(isConsolePath("/\\evil.example")).toBe(false);
    expect(isConsolePath("runs")).toBe(false);
    expect(isConsolePath("/go?to=https://evil.example")).toBe(false);
  });
});
