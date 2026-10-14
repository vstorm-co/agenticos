import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMotionStore } from "@/stores/motion-store";

import { glideOrJump, prefersReducedMotion } from "./motion";

/**
 * The preference is read, not assumed - in both directions.
 *
 * A surface that hardcodes `"smooth"` moves the page under somebody who has said
 * at the operating system that motion makes them ill, and the browser applies no
 * preference to `scrollIntoView` on its own. The person's own Motion setting
 * decides first; the operating system only when it is left on System.
 */

const original = window.matchMedia;
beforeEach(() => {
  useMotionStore.setState({ motion: "system" });
});
afterEach(() => {
  window.matchMedia = original;
});

function asking(reduce: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: reduce }) as unknown as typeof matchMedia;
}

describe("what the reader asked for", () => {
  it("glides when nobody asked for less motion", () => {
    asking(false);

    expect(prefersReducedMotion()).toBe(false);
    expect(glideOrJump()).toBe("smooth");
  });

  it("jumps when they did", () => {
    asking(true);

    expect(prefersReducedMotion()).toBe(true);
    expect(glideOrJump()).toBe("auto");
  });

  it("jumps when the console was told Reduce, whatever the OS says", () => {
    asking(false);
    useMotionStore.setState({ motion: "reduce" });

    expect(prefersReducedMotion()).toBe(true);
  });

  it("glides when the console was told Full, whatever the OS says", () => {
    asking(true);
    useMotionStore.setState({ motion: "full" });

    expect(prefersReducedMotion()).toBe(false);
  });

  it("assumes nothing where there is no browser to ask", () => {
    // Server-rendered, or jsdom without the API. Answering "reduce" would be a
    // claim about somebody nobody has asked.
    window.matchMedia = undefined as unknown as typeof matchMedia;

    expect(prefersReducedMotion()).toBe(false);
  });
});
