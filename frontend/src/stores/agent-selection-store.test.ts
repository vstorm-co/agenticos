import { beforeEach, describe, expect, it } from "vitest";

import { useAgentSelectionStore } from "./agent-selection-store";

describe("Agent selection store", () => {
  beforeEach(() => {
    useAgentSelectionStore.setState({ selectedAgentId: null, defaultAgentId: null });
  });

  it("starts on the general assistant", () => {
    // No implicit default agent, here or on the backend: an unset selection
    // means the assistant, never a guess at which agent the user meant.
    expect(useAgentSelectionStore.getState().selectedAgentId).toBeNull();
  });

  it("replaces the selection rather than accumulating one", () => {
    useAgentSelectionStore.getState().select("a1");
    useAgentSelectionStore.getState().select("a2");
    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a2");
  });

  it("goes back to the assistant", () => {
    useAgentSelectionStore.getState().select("a1");
    useAgentSelectionStore.getState().select(null);
    expect(useAgentSelectionStore.getState().selectedAgentId).toBeNull();
  });

  it("survives a reload", () => {
    // A refresh that silently moves the conversation back to the assistant is
    // the failure worth guarding: the next answer comes from something else.
    useAgentSelectionStore.getState().select("a1");
    expect(localStorage.getItem("agent-selection")).toContain("a1");
  });

  it("has no default agent until one is starred", () => {
    expect(useAgentSelectionStore.getState().defaultAgentId).toBeNull();
  });

  it("keeps the starred default separate from the live selection", () => {
    // Starring is a standing preference, not a switch: it must not move the
    // conversation the user is in, and switching agents must not re-star.
    useAgentSelectionStore.getState().select("a1");
    useAgentSelectionStore.getState().setDefault("a2");
    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a1");
    expect(useAgentSelectionStore.getState().defaultAgentId).toBe("a2");
  });

  it("unstars back to no default", () => {
    useAgentSelectionStore.getState().setDefault("a2");
    useAgentSelectionStore.getState().setDefault(null);
    expect(useAgentSelectionStore.getState().defaultAgentId).toBeNull();
  });

  it("the default survives a reload", () => {
    // The whole point of a default is that a fresh browser starts on it.
    useAgentSelectionStore.getState().setDefault("a2");
    expect(localStorage.getItem("agent-selection")).toContain("a2");
  });
});
