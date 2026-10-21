import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider } from "./theme-provider";
import * as commands from "@/lib/desktop/commands";
import * as shell from "@/lib/desktop/shell";
import { useThemeStore } from "@/stores/theme-store";

/**
 * The theme switch sweeps rather than flips: the class change is wrapped in
 * `document.startViewTransition`, whose snapshot the CSS clip-path animates
 * from the bottom-left corner. What must never happen is the inverse - a
 * change that only works inside a transition. First paint, a browser without
 * the API and a reduced-motion reader all still get the new theme; they get
 * it without the sweep.
 */

function root() {
  return document.documentElement;
}

/**
 * A startViewTransition stub that records the call and runs the mutation. Its
 * `ready` is returned, so a test can see whether a rejection - a browser skipping
 * the transition - has a handler.
 */
function stubViewTransition() {
  const ready = { catch: vi.fn() };
  const spy = vi.fn((update: () => void) => {
    update();
    return { ready, finished: Promise.resolve() };
  });
  Object.defineProperty(document, "startViewTransition", {
    configurable: true,
    writable: true,
    value: spy,
  });
  return Object.assign(spy, { ready });
}

function reducedMotion(matches: boolean) {
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches: query.includes("prefers-reduced-motion") ? matches : false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

beforeEach(() => {
  // The motion preference is a mock that outlives the test that set it.
  reducedMotion(false);
  root().classList.remove("light", "dark");
  useThemeStore.setState({ theme: "light", look: "standard" });
});

afterEach(() => {
  Reflect.deleteProperty(document, "startViewTransition");
  Reflect.deleteProperty(document, "visibilityState");
});

describe("the animated theme switch", () => {
  it("applies the first paint directly - there is nothing on screen to sweep away", () => {
    const transition = stubViewTransition();

    render(<ThemeProvider>{null}</ThemeProvider>);

    expect(root().classList.contains("light")).toBe(true);
    expect(transition).not.toHaveBeenCalled();
  });

  it("sweeps a real change through a view transition", () => {
    const transition = stubViewTransition();
    root().classList.add("light");

    useThemeStore.setState({ theme: "dark" });
    render(<ThemeProvider>{null}</ThemeProvider>);

    expect(transition).toHaveBeenCalledTimes(1);
    expect(root().classList.contains("dark")).toBe(true);
    expect(root().classList.contains("light")).toBe(false);
  });

  it("still changes the theme in a browser without the API", () => {
    root().classList.add("light");

    useThemeStore.setState({ theme: "dark" });
    render(<ThemeProvider>{null}</ThemeProvider>);

    expect(root().classList.contains("dark")).toBe(true);
  });

  it("changes without the sweep for a reader who asked for reduced motion", () => {
    const transition = stubViewTransition();
    reducedMotion(true);
    root().classList.add("light");

    useThemeStore.setState({ theme: "dark" });
    render(<ThemeProvider>{null}</ThemeProvider>);

    expect(transition).not.toHaveBeenCalled();
    expect(root().classList.contains("dark")).toBe(true);
  });

  it("changes without the sweep in a tab that is not on screen", () => {
    const transition = stubViewTransition();
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    root().classList.add("light");

    useThemeStore.setState({ theme: "dark" });
    render(<ThemeProvider>{null}</ThemeProvider>);

    expect(transition).not.toHaveBeenCalled();
    expect(root().classList.contains("dark")).toBe(true);
  });

  it("handles the browser skipping the sweep, which still applies the theme", () => {
    // A tab hidden mid-transition is skipped and its `ready` rejects; unhandled,
    // that surfaced as "Skipped ViewTransition due to document being hidden".
    const transition = stubViewTransition();
    root().classList.add("light");

    useThemeStore.setState({ theme: "dark" });
    render(<ThemeProvider>{null}</ThemeProvider>);

    expect(transition.ready.catch).toHaveBeenCalledTimes(1);
    expect(root().classList.contains("dark")).toBe(true);
  });

  it("starts no transition when the theme is already on screen", () => {
    const transition = stubViewTransition();
    root().classList.add("light");
    root().style.colorScheme = "light";

    render(<ThemeProvider>{null}</ThemeProvider>);

    expect(transition).not.toHaveBeenCalled();
    expect(root().classList.contains("light")).toBe(true);
  });
});

describe("the look", () => {
  afterEach(() => {
    root().removeAttribute("data-look");
    delete window.__AGENTICOS_SHELL__;
    vi.restoreAllMocks();
  });

  it("puts a look on the root, and the standard one as no attribute", () => {
    useThemeStore.setState({ look: "paper" });
    render(<ThemeProvider>{null}</ThemeProvider>);
    expect(root().getAttribute("data-look")).toBe("paper");

    act(() => useThemeStore.setState({ look: "standard" }));
    expect(root().hasAttribute("data-look")).toBe(false);
  });

  it("tells the desktop app's console window, so its material and its next launch follow", () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "macos",
      version: "0.2.0",
      window: "main",
      vibrancy: true,
    };
    const set = vi.spyOn(commands, "setAppearance").mockResolvedValue();
    useThemeStore.setState({ look: "glass", theme: "dark" });
    render(<ThemeProvider>{null}</ThemeProvider>);
    expect(set).toHaveBeenLastCalledWith({ look: "glass", mode: "dark" });
  });

  it("reports a window that would not change, and leaves blobby and browsers out of it", async () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "macos",
      version: "0.2.0",
      window: "main",
      vibrancy: true,
    };
    const refusal = new Error("refused");
    vi.spyOn(commands, "setAppearance").mockRejectedValue(refusal);
    const report = vi.spyOn(shell, "reportShellFailure").mockImplementation(() => {});
    render(<ThemeProvider>{null}</ThemeProvider>);
    await vi.waitFor(() => expect(report).toHaveBeenCalledWith(expect.any(String), refusal));

    window.__AGENTICOS_SHELL__ = {
      platform: "macos",
      version: "0.2.0",
      window: "blobby",
      vibrancy: true,
    };
    const quiet = vi.spyOn(commands, "setAppearance").mockResolvedValue();
    quiet.mockClear();
    render(<ThemeProvider>{null}</ThemeProvider>);
    expect(quiet).not.toHaveBeenCalled();
  });

  it("follows a choice made in another window of the same origin", () => {
    const rehydrate = vi.spyOn(useThemeStore.persist, "rehydrate").mockResolvedValue();
    const { unmount } = render(<ThemeProvider>{null}</ThemeProvider>);
    window.dispatchEvent(new StorageEvent("storage", { key: "motion-storage" }));
    expect(rehydrate).not.toHaveBeenCalled();
    window.dispatchEvent(new StorageEvent("storage", { key: "theme-storage" }));
    expect(rehydrate).toHaveBeenCalledTimes(1);
    unmount();
  });
});

describe("following the system", () => {
  it("changes with the operating system under System, and stops listening when it is left", () => {
    let listener: (() => void) | undefined;
    const query = {
      matches: true,
      addEventListener: vi.fn((_type: string, handler: () => void) => (listener = handler)),
      removeEventListener: vi.fn(),
    };
    vi.mocked(window.matchMedia).mockImplementation(() => query as unknown as MediaQueryList);
    useThemeStore.setState({ theme: "system" });
    const { unmount } = render(<ThemeProvider>{null}</ThemeProvider>);
    act(() => listener?.());
    expect(root().classList.contains("dark")).toBe(true);
    query.matches = false;
    act(() => listener?.());
    expect(root().classList.contains("light")).toBe(true);
    unmount();
    expect(query.removeEventListener).toHaveBeenCalled();
  });
});

describe("a skipped sweep", () => {
  it("is caught, so a browser skipping the transition is not an unhandled rejection", async () => {
    const ready = Promise.reject(new Error("skipped"));
    Object.defineProperty(document, "startViewTransition", {
      configurable: true,
      writable: true,
      value: (update: () => void) => {
        update();
        return { ready, finished: Promise.resolve() };
      },
    });
    root().classList.add("light");
    useThemeStore.setState({ theme: "dark" });
    render(<ThemeProvider>{null}</ThemeProvider>);
    await expect(ready.catch(() => "handled")).resolves.toBe("handled");
    expect(root().classList.contains("dark")).toBe(true);
  });
});
