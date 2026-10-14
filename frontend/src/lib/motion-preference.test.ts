import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MOTION_ATTRIBUTE,
  MOTION_BOOTSTRAP_SCRIPT,
  MOTION_STORAGE_KEY,
  resolveReducedMotion,
  type MotionPreference,
} from "./motion-preference";

/**
 * One resolution, written twice: once as the function the app calls and once as
 * the inline script that runs before the first paint. The table below holds both
 * to the same answers, so the two cannot drift apart.
 */

const CASES: readonly [MotionPreference, boolean, boolean][] = [
  ["system", false, false],
  ["system", true, true],
  ["reduce", false, true],
  ["reduce", true, true],
  ["full", false, false],
  ["full", true, false],
];

const original = window.matchMedia;
afterEach(() => {
  window.matchMedia = original;
  document.documentElement.removeAttribute(MOTION_ATTRIBUTE);
});

function osAsks(reduce: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: reduce }) as unknown as typeof matchMedia;
}

function runBootstrap() {
  // The script is the string the root layout inlines; running it is the test.
  new Function(MOTION_BOOTSTRAP_SCRIPT)();
  return document.documentElement.getAttribute(MOTION_ATTRIBUTE);
}

describe("resolveReducedMotion", () => {
  it.each(CASES)("%s with the OS asking %s reduces: %s", (preference, os, reduced) => {
    expect(resolveReducedMotion(preference, os)).toBe(reduced);
  });
});

describe("the no-flash script", () => {
  it.each(CASES)("%s with the OS asking %s reduces: %s", (preference, os, reduced) => {
    osAsks(os);
    localStorage.setItem(MOTION_STORAGE_KEY, JSON.stringify({ state: { motion: preference } }));

    expect(runBootstrap()).toBe(reduced ? "reduce" : null);
  });

  it("follows the operating system before anything was ever stored", () => {
    osAsks(true);

    expect(runBootstrap()).toBe("reduce");
  });

  it("leaves the attribute to the app when the stored value is unreadable", () => {
    osAsks(true);
    localStorage.setItem(MOTION_STORAGE_KEY, "{not json");

    expect(runBootstrap()).toBeNull();
  });
});
