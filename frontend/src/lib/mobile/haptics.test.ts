import { afterEach, describe, expect, it, vi } from "vitest";

import { haptic } from "./haptics";

const PHONE = { platform: "android", version: "0.1.0", window: "main", vibrancy: false };

afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
  delete window.__TAURI__;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("haptic", () => {
  it("asks the phone app for its own haptics", () => {
    const invoke = vi.fn(async () => null);
    window.__AGENTICOS_SHELL__ = PHONE;
    window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };

    haptic("threshold");
    haptic("success");
    haptic("warning");

    expect(invoke).toHaveBeenNthCalledWith(1, "plugin:haptics|impact_feedback", {
      style: "medium",
    });
    expect(invoke).toHaveBeenNthCalledWith(2, "plugin:haptics|notification_feedback", {
      type: "success",
    });
    expect(invoke).toHaveBeenNthCalledWith(3, "plugin:haptics|notification_feedback", {
      type: "warning",
    });
  });

  it("says where the app refused, and goes on", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    window.__AGENTICOS_SHELL__ = PHONE;
    window.__TAURI__ = {
      core: { invoke: vi.fn(async () => Promise.reject("not allowed")) },
      event: { listen: vi.fn() },
    };

    haptic("threshold");

    await vi.waitFor(() =>
      expect(warn).toHaveBeenCalledWith("desktop", "haptics", expect.anything()),
    );
  });

  it("vibrates in a browser that can, and does nothing in one that cannot", () => {
    const vibrate = vi.fn(() => true);
    vi.stubGlobal("navigator", { vibrate });
    haptic("success");
    expect(vibrate).toHaveBeenCalledWith(20);

    vi.stubGlobal("navigator", {});
    expect(() => haptic("success")).not.toThrow();
  });
});
