import { describe, expect, it } from "vitest";

import { SKILLS_ID, withCapability, withSkills } from "./agent-spec";
import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";

function binding(
  id: string,
  overrides: Partial<CapabilityBindingSpec> = {},
): CapabilityBindingSpec {
  return {
    id,
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: true,
    ...overrides,
  };
}

function spec(overrides: Partial<AgentSpec> = {}): AgentSpec {
  return {
    spec_version: 5,
    name: "Support",
    description: null,
    instructions: "",
    model_profile_id: null,
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    mcp_server_ids: [],
    budget: null,
    ...overrides,
  };
}

describe("withCapability", () => {
  it("adds a binding that publishing will accept", () => {
    const [added] = withCapability([], "charts", true);

    expect(added).toMatchObject({ id: "charts", enabled: true, secret_id: null });
  });

  it("leaves a capability that is already on exactly as it was", () => {
    // Otherwise asking for a state it is already in would silently reset
    // somebody's tool overrides and approval choices.
    const configured = binding("charts", {
      approval: "required",
      tool_approval: { create_chart: "never" },
    });

    expect(withCapability([configured], "charts", true)).toEqual([configured]);
  });

  it("removes the binding when switched off", () => {
    expect(withCapability([binding("charts"), binding("clock")], "charts", false)).toEqual([
      binding("clock"),
    ]);
  });
});

describe("withSkills", () => {
  it("gives the agent the capability that can read the skill it just bound", () => {
    /**
     * The bug this exists for. `skill_ids` resolves skills into the run's
     * resources; the `skills` capability is what turns them into tools. Bound
     * without it, the skills were fetched and thrown away — an agent that
     * silently knew nothing.
     */
    const updated = withSkills(spec(), ["skill-1"]);

    expect(updated.skill_ids).toEqual(["skill-1"]);
    expect(updated.capabilities?.map((entry) => entry.id)).toEqual([SKILLS_ID]);
  });

  it("takes the capability away with the last skill", () => {
    // Left behind it is a capability whose tools answer "no skills", which is
    // worse than not having them: the model asks and is told nothing is there.
    const bound = spec({ skill_ids: ["skill-1"], capabilities: [binding(SKILLS_ID)] });

    const updated = withSkills(bound, []);

    expect(updated.skill_ids).toEqual([]);
    expect(updated.capabilities).toEqual([]);
  });

  it("does not disturb the other capabilities", () => {
    const bound = spec({ capabilities: [binding("charts", { approval: "required" })] });

    const updated = withSkills(bound, ["skill-1"]);

    expect(updated.capabilities?.map((entry) => entry.id)).toEqual(["charts", SKILLS_ID]);
    expect(updated.capabilities?.[0]).toMatchObject({ approval: "required" });
  });

  it("keeps a skills capability somebody configured by hand", () => {
    const configured = binding(SKILLS_ID, { approval: "required" });
    const bound = spec({ skill_ids: ["skill-1"], capabilities: [configured] });

    expect(withSkills(bound, ["skill-1", "skill-2"]).capabilities).toEqual([configured]);
  });
});
