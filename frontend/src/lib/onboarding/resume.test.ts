import { beforeEach, describe, expect, it, vi } from "vitest";

import { stashFlow, takeStashedFlow } from "./resume";

const KEY = "agenticos:onboarding-flow";

const RUNNING = {
  flowId: "create-agent" as const,
  index: 7,
  choices: { "flow-agent-mcp-ask": "yes" as const },
  flowAgentId: "a-1",
};

beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe("stashFlow / takeStashedFlow", () => {
  it("carries a running flow across one page load and no further", () => {
    // Connecting an MCP server over OAuth leaves the app and returns through a
    // second full load, emptying the store. Read once, so the load after the
    // redirect resumes and a later reload starts clean.
    stashFlow(RUNNING);
    expect(takeStashedFlow()).toEqual(RUNNING);
    expect(takeStashedFlow()).toBeNull();
  });

  it("reads nothing when no flow was stowed", () => {
    expect(takeStashedFlow()).toBeNull();
  });

  it("drops a value this build could not resume", () => {
    // The value outlives a deploy. A flow that no longer exists, or an index that
    // is not one, would resume the walk in the middle of a different step list.
    for (const bad of [
      "not json at all",
      JSON.stringify(null),
      JSON.stringify("a string"),
      JSON.stringify({ ...RUNNING, flowId: "create-something-else" }),
      JSON.stringify({ ...RUNNING, flowId: 3 }),
      JSON.stringify({ ...RUNNING, index: -1 }),
      JSON.stringify({ ...RUNNING, index: 1.5 }),
      JSON.stringify({ ...RUNNING, index: "7" }),
      JSON.stringify({ ...RUNNING, choices: null }),
      JSON.stringify({ ...RUNNING, choices: "yes" }),
      JSON.stringify({ ...RUNNING, flowAgentId: 42 }),
    ]) {
      sessionStorage.setItem(KEY, bad);
      expect(takeStashedFlow()).toBeNull();
      expect(sessionStorage.getItem(KEY)).toBeNull();
    }
  });

  it("keeps a flow that never captured an agent", () => {
    stashFlow({ ...RUNNING, flowAgentId: null });
    expect(takeStashedFlow()?.flowAgentId).toBeNull();
  });

  it("survives storage refusing to hold it", () => {
    // Private mode, or a full quota. Losing the walk is what already happened
    // without this; it must not also break the navigation that was under way.
    // Spy the instance, not `Storage.prototype`: on a Node that ships its own
    // storage the two are different objects. Asserting nothing was stored fails
    // a spy that missed, where asserting only "did not throw" would not.
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => stashFlow(RUNNING)).not.toThrow();
    expect(takeStashedFlow()).toBeNull();
  });

  it("survives storage refusing to be read", () => {
    // A real flow is present, so a missed spy would return it rather than null -
    // which is what let this `catch` read as covered while never running (#915).
    stashFlow(RUNNING);
    vi.spyOn(sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(takeStashedFlow()).toBeNull();
  });
});
