import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider } from "./theme-provider";
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

/** A startViewTransition stub that records the call and runs the mutation. */
function stubViewTransition() {
  const spy = vi.fn((update: () => void) => {
    update();
    return { finished: Promise.resolve() };
  });
  Object.defineProperty(document, "startViewTransition", {
    configurable: true,
    writable: true,
    value: spy,
  });
  return spy;
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
  root().classList.remove("light", "dark");
  useThemeStore.setState({ theme: "light" });
});

afterEach(() => {
  Reflect.deleteProperty(document, "startViewTransition");
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

  it("starts no transition when the theme is already on screen", () => {
    const transition = stubViewTransition();
    root().classList.add("light");
    root().style.colorScheme = "light";

    render(<ThemeProvider>{null}</ThemeProvider>);

    expect(transition).not.toHaveBeenCalled();
    expect(root().classList.contains("light")).toBe(true);
  });
});
