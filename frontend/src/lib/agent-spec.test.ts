import { describe, expect, it } from "vitest";

import {
  DEFAULT_SUBAGENTS_CONFIG,
  delegationNameClashes,
  duplicateDelegateIds,
  newSpecialist,
  pinStatus,
  readSubagentsConfig,
  SKILLS_ID,
  specialistNameError,
  SUBAGENTS_ID,
  VERSION_HISTORY_LIMIT,
  withCapability,
  withSkills,
} from "./agent-spec";
import type { AgentSpec, AgentVersion, CapabilityBindingSpec } from "@/types/agents";

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
     * without it, the skills were fetched and thrown away - an agent that
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

/** One published version of a delegate, as its history reports it. */
function version(number: number): AgentVersion {
  return { id: `v${number}`, version: number, note: null, published_by_user_id: null };
}

describe("readSubagentsConfig", () => {
  it("fills in the shipped defaults for a binding switched on this session", () => {
    // A binding created by the picker carries `{}`. Reading depth 0 and no mode
    // out of it would describe an agent that will in fact delegate once,
    // synchronously.
    expect(readSubagentsConfig(binding(SUBAGENTS_ID))).toEqual(DEFAULT_SUBAGENTS_CONFIG);
  });

  it("keeps what the spec actually says", () => {
    const stored = binding(SUBAGENTS_ID, { config: { mode: "async", max_depth: 3 } });

    expect(readSubagentsConfig(stored)).toMatchObject({ mode: "async", max_depth: 3 });
    expect(readSubagentsConfig(stored).max_fanout).toBe(3);
  });

  it("reads an unbound capability as the defaults rather than throwing", () => {
    expect(readSubagentsConfig(undefined).inline).toEqual([]);
  });
});

describe("specialistNameError", () => {
  it("refuses a name the model cannot address", () => {
    expect(specialistNameError("")).toBe("specialistNameBlank");
  });

  it("refuses what a tool argument cannot carry", () => {
    expect(specialistNameError("research topics")).toBe("specialistNamePattern");
    expect(specialistNameError("a".repeat(65))).toBe("specialistNameTooLong");
  });

  it("accepts the shape the backend's pattern accepts", () => {
    expect(specialistNameError("summarise_3-bullets")).toBeNull();
  });
});

describe("delegationNameClashes", () => {
  it("names what a delegate and a specialist both answer to", () => {
    // The model addresses a subagent by name, so the second of two shadows the
    // first and is never reached.
    const clashes = delegationNameClashes(
      ["researcher"],
      [{ ...newSpecialist(), name: "researcher" }],
    );

    expect([...clashes]).toEqual(["researcher"]);
  });

  it("does not treat two unnamed specialists as a clash", () => {
    // Both are blank because neither has been filled in yet, which is a form in
    // progress rather than a spec that cannot publish - the blank name is
    // already refused on its own.
    const clashes = delegationNameClashes([], [newSpecialist(), newSpecialist()]);

    expect(clashes.size).toBe(0);
  });

  it("says nothing about names that are all different", () => {
    expect(delegationNameClashes(["a"], [{ ...newSpecialist(), name: "b" }]).size).toBe(0);
  });
});

describe("duplicateDelegateIds", () => {
  it("finds the agent pinned twice, which the spec itself refuses", () => {
    const twice = duplicateDelegateIds([
      { agent_id: "a1", agent_version_id: "v1" },
      { agent_id: "a1", agent_version_id: "v2" },
    ]);

    expect([...twice]).toEqual(["a1"]);
  });

  it("is empty for one pin each", () => {
    expect(
      duplicateDelegateIds([
        { agent_id: "a1", agent_version_id: "v1" },
        { agent_id: "a2", agent_version_id: "v1" },
      ]).size,
    ).toBe(0);
  });
});

/**
 * Where a pin stands against the delegate's own history.
 *
 * The most important thing this file computes: a pin is what keeps a delegate's
 * behaviour stable under a published parent, and the cost is that a fix to the
 * delegate does not arrive. Nothing else in the product would ever say so.
 */
describe("pinStatus", () => {
  it("says how many versions a pin is behind, and what the latest is", () => {
    const status = pinStatus([version(7), version(5), version(3)], "v3", "v7");

    expect(status).toEqual({ kind: "behind", version: 3, latest: 7, by: 4 });
  });

  it("recognises the pin that is already what the delegate publishes", () => {
    expect(pinStatus([version(2), version(1)], "v2", "v2")).toEqual({
      kind: "current",
      version: 2,
    });
  });

  it("calls a pin whose version is gone gone, because that fails the run", () => {
    // Never a quiet fall back to the current version: the reason to pin is that
    // nothing changes without a decision.
    expect(pinStatus([version(2)], "v1", "v2")).toEqual({ kind: "gone" });
  });

  it("will not call a pin gone when the history it read may be truncated", () => {
    // `list_versions` returns at most fifty, newest first. A pin older than
    // fifty publishes is absent from a complete-as-far-as-it-goes history, and
    // "deleted" and "off the end of the page" have different fixes.
    const full = Array.from({ length: VERSION_HISTORY_LIMIT }, (_, index) => version(index + 51));

    expect(pinStatus(full, "v1", "v100")).toEqual({ kind: "unknown" });
  });

  it("says nothing while the history has not been read", () => {
    expect(pinStatus([], "v1", "v2")).toEqual({ kind: "unknown" });
  });

  it("says nothing rather than guessing when the delegate publishes nothing", () => {
    // An agent unpublished since it was pinned has no current version to
    // compare against, and inventing one would report a stale pin as current.
    expect(pinStatus([version(1)], "v1", null)).toEqual({ kind: "unknown" });
  });
});
