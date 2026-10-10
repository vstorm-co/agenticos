import { afterEach, describe, expect, it, vi } from "vitest";

import {
  bubbleFor,
  pageOf,
  readPreferences,
  resetSilenced,
  setBubblesOff,
  silencePage,
} from "./assistant-bubbles";

const QUIET = { pendingApprovals: 0, noAgents: false };

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("bubbleFor", () => {
  it("puts what is waiting before everything else", () => {
    expect(bubbleFor("/agents", { pendingApprovals: 2, noAgents: true }, 1)).toBe("approvals");
    expect(bubbleFor("/agents", { pendingApprovals: 0, noAgents: true }, 1)).toBe("firstSteps");
  });

  it("speaks to the page the reader is on, with or without a locale", () => {
    expect(bubbleFor("/pl/agents", QUIET, 1)).toBe("agents");
    expect(bubbleFor("/agents/abc", QUIET, 1)).toBe("agent");
    expect(bubbleFor("/kb/1", QUIET, 1)).toBe("knowledge");
    expect(bubbleFor("/rag", QUIET, 1)).toBe("knowledge");
    expect(bubbleFor("/runs", QUIET, 1)).toBe("runs");
    expect(bubbleFor("/skills", QUIET, 1)).toBe("skills");
    expect(bubbleFor("/settings/api-keys", QUIET, 1)).toBe("settings");
  });

  it("offers a tip on one page view in four, cycling through them", () => {
    expect(bubbleFor("/chat", QUIET, 1)).toBeNull();
    expect(bubbleFor("/chat", QUIET, 0)).toBe("tipMcp");
    expect(bubbleFor("/chat", QUIET, 4)).toBe("tipVariables");
    expect(bubbleFor("/chat", QUIET, 12)).toBe("tipQuestions");
    expect(bubbleFor("/chat", QUIET, 16)).toBe("tipMcp");
  });

  it("knows a page by its path without the locale", () => {
    expect(pageOf("/de")).toBe("/");
    expect(pageOf("/de/kb")).toBe("/kb");
    expect(pageOf("/kb")).toBe("/kb");
  });
});

describe("preferences", () => {
  it("remembers a silenced page once, and the switch", () => {
    silencePage("/pl/agents");
    silencePage("/agents");
    setBubblesOff(true);

    expect(readPreferences()).toEqual({ silenced: ["/agents"], off: true });
  });

  it("lets every silenced page speak again without touching the switch", () => {
    silencePage("/agents");
    setBubblesOff(true);

    resetSilenced();

    expect(readPreferences()).toEqual({ silenced: [], off: true });
  });

  it("reads anything unreadable as the default", () => {
    localStorage.setItem("assistant-bubbles", "not json");
    expect(readPreferences()).toEqual({ silenced: [], off: false });

    localStorage.setItem("assistant-bubbles", JSON.stringify({ silenced: [1, "/kb"], off: "yes" }));
    expect(readPreferences()).toEqual({ silenced: ["/kb"], off: false });

    localStorage.setItem("assistant-bubbles", JSON.stringify({ off: true }));
    expect(readPreferences()).toEqual({ silenced: [], off: true });

    localStorage.setItem("assistant-bubbles", "42");
    expect(readPreferences()).toEqual({ silenced: [], off: false });
  });

  it("survives storage that refuses to be written", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });

    expect(() => setBubblesOff(true)).not.toThrow();
  });
});
