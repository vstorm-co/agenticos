import { describe, expect, it } from "vitest";

import { isSystemAgent, SYSTEM_AGENT_KINDS } from "./system-agents";

describe("isSystemAgent", () => {
  it("is every kind but the agents people use", () => {
    expect(SYSTEM_AGENT_KINDS.every(isSystemAgent)).toBe(true);
    expect(isSystemAgent("agent")).toBe(false);
  });

  it("treats an agent whose kind is not known yet as an ordinary one", () => {
    expect(isSystemAgent(undefined)).toBe(false);
  });
});
