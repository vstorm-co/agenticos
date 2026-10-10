import { beforeEach, describe, expect, it, vi } from "vitest";

import { askedToTest, readTestPanel, writeTestPanel } from "./test-panel-state";

beforeEach(() => window.localStorage.clear());

describe("the test panel's remembered state", () => {
  it("starts closed, on the draft, with nothing pinned", () => {
    expect(readTestPanel("a1")).toEqual({
      open: false,
      width: 440,
      mode: "draft",
      compare: null,
      pinned: [],
    });
  });

  it("keeps each agent's own", () => {
    writeTestPanel("a1", {
      open: true,
      width: 600,
      mode: "env-1",
      compare: "draft",
      pinned: ["refunds?"],
    });

    expect(readTestPanel("a1")).toEqual({
      open: true,
      width: 600,
      mode: "env-1",
      compare: "draft",
      pinned: ["refunds?"],
    });
    expect(readTestPanel("a2").open).toBe(false);
  });

  it("reads past whatever else is stored there", () => {
    window.localStorage.setItem(
      "agenticos:test-panel:a1",
      JSON.stringify({ open: "yes", width: "wide", mode: 3, compare: 1, pinned: ["ok", 4] }),
    );

    expect(readTestPanel("a1")).toEqual({
      open: false,
      width: 440,
      mode: "draft",
      compare: null,
      pinned: ["ok"],
    });

    window.localStorage.setItem("agenticos:test-panel:a1", JSON.stringify({ pinned: "x" }));
    expect(readTestPanel("a1").pinned).toEqual([]);
  });

  it("starts from defaults where storage refuses, and stores nothing then", () => {
    window.localStorage.setItem("agenticos:test-panel:a1", "{not json");
    expect(readTestPanel("a1").mode).toBe("draft");

    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() =>
      writeTestPanel("a1", { open: true, width: 440, mode: "draft", compare: null, pinned: [] }),
    ).not.toThrow();
    setItem.mockRestore();
  });
});

describe("a link that asks for the test panel (#2074)", () => {
  it("is ?test=open, and nothing else", () => {
    window.history.replaceState(null, "", "/agents/a1?test=open");
    expect(askedToTest()).toBe(true);

    window.history.replaceState(null, "", "/agents/a1?test=1");
    expect(askedToTest()).toBe(false);
    window.history.replaceState(null, "", "/");
  });

  it("is not asked for where the address cannot be read", () => {
    const original = window.location;
    Object.defineProperty(window, "location", { value: undefined, configurable: true });
    expect(askedToTest()).toBe(false);
    Object.defineProperty(window, "location", { value: original, configurable: true });
  });
});
