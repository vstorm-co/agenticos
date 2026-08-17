import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  hasUsedPageHelp,
  hasUsedPageHelpOnServer,
  markPageHelpUsed,
  subscribeToPageHelp,
} from "./help-hint";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("page-help hint", () => {
  it("hints until the control is first used, then never again", () => {
    expect(hasUsedPageHelp()).toBe(false);
    markPageHelpUsed();
    expect(hasUsedPageHelp()).toBe(true);
  });

  it("treats storage it cannot read as used", () => {
    // A hint that cannot remember being dismissed would pulse in every page
    // header, forever — worse than never hinting at all.
    // Spied on the instance, not `Storage.prototype`: the test setup replaces
    // `localStorage` with its own object (Node 22 ships a disabled built-in that
    // shadows jsdom's), so the prototype is not in this object's chain.
    vi.spyOn(localStorage, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(hasUsedPageHelp()).toBe(true);
  });

  it("survives storage refusing to record the press", () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => markPageHelpUsed()).not.toThrow();
  });

  it("renders as used on the server, so no HTML arrives already pulsing", () => {
    expect(hasUsedPageHelpOnServer()).toBe(true);
  });

  it("tells every header at once, and stops telling an unsubscribed one", () => {
    // The "?" is in twenty page headers; the first press has to settle all of them.
    const listener = vi.fn();
    const unsubscribe = subscribeToPageHelp(listener);
    markPageHelpUsed();
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    markPageHelpUsed();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
