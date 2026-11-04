import { afterEach, describe, expect, it, vi } from "vitest";

import { ShellError } from "@/lib/desktop/shell";

import { parseShared, takeShared } from "./shared";

afterEach(() => {
  delete window.__TAURI__;
});

describe("parseShared", () => {
  it("reads nothing shared, and text with files as the composer takes them", async () => {
    expect(parseShared(null)).toBeNull();
    const shared = parseShared({
      text: "look",
      files: [{ name: "a.txt", mimeType: "text/plain", data: btoa("hi") }],
      refused: ["big.mov"],
    });
    expect(shared?.text).toBe("look");
    expect(shared?.refused).toEqual(["big.mov"]);
    expect(shared?.files[0]?.name).toBe("a.txt");
    expect(shared?.files[0]?.type).toBe("text/plain");
    expect(await shared?.files[0]?.text()).toBe("hi");
  });

  it("refuses a shape it does not know", () => {
    for (const value of [
      { text: "x", files: [{ name: "a" }], refused: [] },
      { text: "x", files: ["a"], refused: [] },
      { text: "x", files: [], refused: [1] },
      { files: [] },
      "x",
    ]) {
      expect(() => parseShared(value)).toThrow(ShellError);
    }
  });
});

describe("takeShared", () => {
  it("asks the app", async () => {
    const invoke = vi.fn(async () => null);
    window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };
    await expect(takeShared()).resolves.toBeNull();
    expect(invoke).toHaveBeenCalledWith("take_shared", undefined);
  });
});
