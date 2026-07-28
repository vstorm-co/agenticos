import { describe, expect, it } from "vitest";

import { accessSummary } from "./agent-card";
import type { Agent } from "@/types/agents";

function agent(overrides: Partial<Agent>): Agent {
  return {
    id: "a1",
    slug: "support",
    name: "Support",
    description: null,
    status: "published",
    visibility: "private",
    owner_user_id: null,
    current_version_id: null,
    ...overrides,
  };
}

describe("accessSummary", () => {
  it("an org-visible agent reads as the organization's, whatever the grant count", () => {
    expect(accessSummary(agent({ visibility: "org", shared_user_count: 5 })).label).toBe(
      "Organization",
    );
  });

  it("a team-visible agent reads as the team's", () => {
    expect(accessSummary(agent({ visibility: "team" })).label).toBe("Team");
  });

  it("a private agent with grants says how many people were handed it", () => {
    expect(accessSummary(agent({ visibility: "private", shared_user_count: 3 })).label).toBe(
      "Shared with 3",
    );
  });

  it("a private agent nobody was handed reads as private, including when the listing omits the count", () => {
    expect(accessSummary(agent({ visibility: "private", shared_user_count: 0 })).label).toBe(
      "Private",
    );
    expect(accessSummary(agent({ visibility: "private" })).label).toBe("Private");
  });
});
