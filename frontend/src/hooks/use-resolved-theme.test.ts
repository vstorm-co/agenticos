import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useResolvedTheme } from "./use-resolved-theme";
import { useThemeStore } from "@/stores/theme-store";

/** Drives `matchMedia` so the system half of the answer can be moved. */
function stubSystem(prefersDark: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    matches: prefersDark,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => query),
  );
  return {
    change(nowDark: boolean) {
      query.matches = nowDark;
      act(() => listeners.forEach((fn) => fn()));
    },
    get listenerCount() {
      return listeners.size;
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  useThemeStore.setState({ theme: "system" });
});

describe("useResolvedTheme", () => {
  it("answers with the chosen theme, whatever the system prefers", () => {
    stubSystem(true);
    useThemeStore.setState({ theme: "light" });

    expect(renderHook(() => useResolvedTheme()).result.current).toBe("light");
  });

  it("follows the system when nothing was chosen", () => {
    stubSystem(true);
    useThemeStore.setState({ theme: "system" });

    expect(renderHook(() => useResolvedTheme()).result.current).toBe("dark");
  });

  it("re-answers when the system theme changes under it", () => {
    // The class on <html> handles this case by itself; a prop does not, which
    // is the whole reason this hook subscribes rather than reads once.
    const system = stubSystem(false);
    useThemeStore.setState({ theme: "system" });
    const { result } = renderHook(() => useResolvedTheme());

    expect(result.current).toBe("light");

    system.change(true);

    expect(result.current).toBe("dark");
  });

  it("stops listening when it goes away", () => {
    const system = stubSystem(false);
    const { unmount } = renderHook(() => useResolvedTheme());

    expect(system.listenerCount).toBe(1);

    unmount();

    expect(system.listenerCount).toBe(0);
  });
});
