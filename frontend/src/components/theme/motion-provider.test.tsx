import { act, render, screen } from "@testing-library/react";
import { useReducedMotionConfig } from "motion/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMotionStore } from "@/stores/motion-store";

import { MotionProvider } from "./motion-provider";

/**
 * The preference reaches both dialects: the `data-motion` attribute every CSS
 * rule keys off, and motion/react through `MotionConfig`.
 */

function root() {
  return document.documentElement;
}

/** What motion/react's own animations are told, read the way they read it. */
function MotionProbe() {
  return <span data-testid="motion">{String(useReducedMotionConfig())}</span>;
}

function osAsks(reduce: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: reduce,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof matchMedia;
}

const original = window.matchMedia;
beforeEach(() => {
  useMotionStore.setState({ motion: "system" });
  root().removeAttribute("data-motion");
});
afterEach(() => {
  window.matchMedia = original;
  root().removeAttribute("data-motion");
});

describe("MotionProvider", () => {
  it("marks the root and reduces motion/react when the OS asks, on System", () => {
    osAsks(true);

    render(
      <MotionProvider>
        <MotionProbe />
      </MotionProvider>,
    );

    expect(root()).toHaveAttribute("data-motion", "reduce");
    expect(screen.getByTestId("motion")).toHaveTextContent("true");
  });

  it("leaves the root unmarked and motion/react free under Full, whatever the OS says", () => {
    osAsks(true);
    useMotionStore.setState({ motion: "full" });
    root().setAttribute("data-motion", "reduce");

    render(
      <MotionProvider>
        <MotionProbe />
      </MotionProvider>,
    );

    expect(root()).not.toHaveAttribute("data-motion");
    expect(screen.getByTestId("motion")).toHaveTextContent("false");
  });

  it("follows the preference as it changes", () => {
    osAsks(false);
    render(
      <MotionProvider>
        <MotionProbe />
      </MotionProvider>,
    );
    expect(root()).not.toHaveAttribute("data-motion");

    act(() => useMotionStore.getState().setMotion("reduce"));
    expect(root()).toHaveAttribute("data-motion", "reduce");
    expect(screen.getByTestId("motion")).toHaveTextContent("true");

    act(() => useMotionStore.getState().setMotion("system"));
    expect(root()).not.toHaveAttribute("data-motion");
  });
});
