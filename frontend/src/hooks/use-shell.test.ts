import { renderHook } from "@testing-library/react";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import { useShell } from "./use-shell";

afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
});

describe("useShell", () => {
  it("is null in a browser", () => {
    expect(renderHook(() => useShell()).result.current).toBeNull();
  });

  it("is the shell's announcement inside the app, the same object on every render", () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "windows",
      version: "0.2.0",
      window: "quick-ask",
      vibrancy: true,
    };
    const { result, rerender } = renderHook(() => useShell());
    const first = result.current;
    rerender();
    expect(first).toMatchObject({ platform: "windows", window: "quick-ask" });
    expect(result.current).toBe(first);
  });

  it("renders as a browser on the server, so hydration agrees, and lets go on unmount", () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "macos",
      version: "0.2.0",
      window: "main",
      vibrancy: true,
    };
    function Probe() {
      return createElement("span", null, useShell()?.platform ?? "browser");
    }
    expect(renderToString(createElement(Probe))).toContain("browser");
    const { unmount } = renderHook(() => useShell());
    expect(unmount).not.toThrow();
  });
});
