import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  appHistoryState,
  previousEntryInApp,
  takeOwnTraversal,
  traverseHistory,
} from "./history-entries";

/** A Navigation API whose entries are `urls`, standing on the last one. */
function entries(...urls: string[]) {
  const list = urls.map((url, index) => ({ url, index }));
  Object.defineProperty(window, "navigation", {
    configurable: true,
    value: { currentEntry: list.at(-1), entries: () => list },
  });
}

const origin = window.location.origin;

afterEach(() => {
  Reflect.deleteProperty(window, "navigation");
  vi.restoreAllMocks();
});

describe("appHistoryState", () => {
  it("keeps what the app wrote and leaves the router's keys for the router to fill in", () => {
    window.history.replaceState(
      { __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: ["tree"], __urlOverlay: "case" },
      "",
      "/datasets/d1",
    );
    expect(appHistoryState()).toEqual({ __urlOverlay: "case" });
  });

  it("is empty for an entry nobody wrote state into", () => {
    window.history.replaceState(null, "", "/datasets/d1");
    expect(appHistoryState()).toEqual({});
  });
});

describe("previousEntryInApp", () => {
  it("is true when Back lands on another page of this app", () => {
    entries(`${origin}/datasets/d1?tab=evals`, `${origin}/agents/a1/evals/r1`);
    expect(previousEntryInApp()).toBe(true);
  });

  it("is false on the first entry, as after a link opened in a new tab", () => {
    entries(`${origin}/agents/a1/evals/r1`);
    expect(previousEntryInApp()).toBe(false);
  });

  it("is false where the browser has no Navigation API", () => {
    expect(previousEntryInApp()).toBe(false);
  });

  it("is false when Back would land on signing in, in any locale", () => {
    entries(`${origin}/login`, `${origin}/dashboard`);
    expect(previousEntryInApp()).toBe(false);
    entries(`${origin}/pl/auth/callback?code=x`, `${origin}/pl/dashboard`);
    expect(previousEntryInApp()).toBe(false);
  });

  it("is true for a locale-prefixed page of the app", () => {
    entries(`${origin}/de/datasets`, `${origin}/de/datasets/d1`);
    expect(previousEntryInApp()).toBe(true);
  });

  it("is false for an entry another site left without a readable address", () => {
    Object.defineProperty(window, "navigation", {
      configurable: true,
      value: { currentEntry: { index: 1 }, entries: () => [{ url: null, index: 0 }] },
    });
    expect(previousEntryInApp()).toBe(false);
  });

  it("is false for another origin's entry", () => {
    entries("https://example.com/docs", `${origin}/dashboard`);
    expect(previousEntryInApp()).toBe(false);
  });
});

describe("traverseHistory", () => {
  beforeEach(() => {
    takeOwnTraversal();
  });

  it("takes one step however many ask for it before the step lands", () => {
    const go = vi.spyOn(window.history, "go").mockImplementation(() => {});
    traverseHistory(-2);
    traverseHistory(-2);
    expect(go).toHaveBeenCalledTimes(1);
    expect(go).toHaveBeenCalledWith(-2);

    expect(takeOwnTraversal()).toBe(true);
    expect(takeOwnTraversal()).toBe(false);
    traverseHistory(-1);
    expect(go).toHaveBeenLastCalledWith(-1);
  });
});
