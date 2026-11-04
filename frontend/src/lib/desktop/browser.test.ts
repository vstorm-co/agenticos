import { beforeEach, describe, expect, it, vi } from "vitest";
import { controlNativeBrowser, nativeBrowserState } from "./browser";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("./shell", async (original) => ({
  ...(await original<typeof import("./shell")>()),
  invokeShell: invoke,
}));
beforeEach(() => invoke.mockReset());

describe("native browser boundary", () => {
  it("sends controls through the console's bounded shell command", async () => {
    invoke.mockResolvedValue(null);
    await controlNativeBrowser("tab", "hide");
    expect(invoke).toHaveBeenLastCalledWith("native_browser_view", { id: "tab", action: "hide" });
    const bounds = { x: 10, y: 40, width: 800, height: 600 };
    await controlNativeBrowser("tab", "show", { bounds });
    expect(invoke).toHaveBeenLastCalledWith("native_browser_view", {
      id: "tab",
      action: "show",
      bounds,
    });
  });
  it("reads location and local hold state", async () => {
    const state = { url: "https://example.test/", title: "Example", held: true };
    invoke.mockResolvedValue(state);
    expect(await nativeBrowserState("tab")).toEqual(state);
  });
  it.each([
    null,
    "bad",
    {},
    { url: 1 },
    { url: "x" },
    { url: "x", title: 1 },
    { url: "x", title: "Title" },
    { url: "x", title: "Title", held: 1 },
  ])("refuses malformed shell state %j", async (value) => {
    invoke.mockResolvedValue(value);
    await expect(nativeBrowserState("tab")).rejects.toThrow();
  });
});
