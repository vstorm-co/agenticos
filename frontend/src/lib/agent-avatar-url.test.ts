import { describe, expect, it } from "vitest";
import { agentAvatarUrl } from "./agent-avatar-url";

describe("agentAvatarUrl", () => {
  it("carries the active organization and separates tenants in the image URL", () => {
    expect(agentAvatarUrl("agent", "team-a")).toBe(
      "/api/agents/agent/avatar?organization_id=team-a",
    );
    expect(agentAvatarUrl("agent", "team-b")).not.toBe(agentAvatarUrl("agent", "team-a"));
  });
  it("preserves personal organization resolution when no organization was selected", () => {
    expect(agentAvatarUrl("agent", null)).toBe("/api/agents/agent/avatar");
  });
  it("keeps the upload version alongside the organization", () => {
    expect(agentAvatarUrl("agent", "team", 2)).toBe(
      "/api/agents/agent/avatar?organization_id=team&v=2",
    );
  });
});
