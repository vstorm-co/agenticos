import { describe, expect, it } from "vitest";

import {
  forSystemAgent,
  isSystemAgent,
  sharedWithOrganization,
  SYSTEM_AGENT_KINDS,
  systemAgentOffers,
  verdictKind,
} from "./system-agents";
import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";

describe("isSystemAgent", () => {
  it("is every kind but the agents people use", () => {
    expect(SYSTEM_AGENT_KINDS.every(isSystemAgent)).toBe(true);
    expect(isSystemAgent("agent")).toBe(false);
  });

  it("treats an agent whose kind is not known yet as an ordinary one", () => {
    expect(isSystemAgent(undefined)).toBe(false);
  });
});

describe("verdictKind", () => {
  it("is the judge's grade and the classifier's label", () => {
    expect(verdictKind("judge")).toBe("judge");
    expect(verdictKind("classifier")).toBe("classifier");
  });

  it("is nothing for a kind that drafts, and for an ordinary agent", () => {
    for (const kind of ["drafter", "generator", "improver", "agent", undefined] as const) {
      expect(verdictKind(kind)).toBeUndefined();
    }
  });
});

describe("systemAgentOffers", () => {
  it.each(SYSTEM_AGENT_KINDS.filter((kind) => kind !== "classifier"))(
    "offers a %s how it reasons, its context, its skills and a knowledge search",
    (kind) => {
      for (const id of ["thinking", "context", "skills", "knowledge"]) {
        expect(systemAgentOffers(kind, id)).toBe(true);
      }
    },
  );

  it("offers a classifier no skills", () => {
    expect(systemAgentOffers("classifier", "skills")).toBe(false);
    expect(systemAgentOffers("classifier", "context")).toBe(true);
    expect(systemAgentOffers("classifier", "knowledge")).toBe(true);
  });

  it("offers no capability that reaches past the prompt", () => {
    for (const id of ["web_search", "sandbox", "subagents", "memory_files"]) {
      expect(systemAgentOffers("judge", id)).toBe(false);
    }
  });
});

describe("sharedWithOrganization", () => {
  const ORG = { id: "f1", visibility: "org" };
  const NARROW = { id: "f2", visibility: "private" };

  it("keeps only what the whole organization shares", () => {
    expect(sharedWithOrganization([ORG, NARROW], 2, [])).toEqual({ items: [ORG], total: 1 });
  });

  it("keeps a narrower pick the agent already holds, so it can be taken off", () => {
    expect(sharedWithOrganization([ORG, NARROW], 2, ["f2"])).toEqual({
      items: [ORG, NARROW],
      total: 2,
    });
  });

  it("keeps the total of a set it holds only part of", () => {
    // A gallery names a chosen id it does not list as deleted only once it holds
    // every row, which a narrowed page of forty is not.
    expect(sharedWithOrganization([ORG, NARROW], 40, [])).toEqual({ items: [ORG], total: 40 });
  });
});

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

/** What a judge's draft can still hold from before its save refused all this. */
const STORED: AgentSpec = {
  name: "Refunds judge",
  instructions: "Grade the answer.",
  starters: ["Grade this"],
  model_profile_id: "p1",
  model_settings: { temperature: 0 },
  capabilities: [
    binding("thinking", { config: { effort: "high" } }),
    binding("web_search"),
    binding("context", { approval: "required", tool_approval: { read_context: "required" } }),
    binding("memory_files", { enabled: false }),
    binding("skills"),
    binding("knowledge", {
      config: { top_k: 4 },
      approval: "required",
      tool_approval: { search_knowledge: "required" },
    }),
  ],
  collection_ids: ["kb1"],
  skill_ids: ["s1"],
  context_ids: ["c1"],
  mcp_servers: [
    { account: "organization", connection_id: "m1", allowed_tools: null, approval: "none" },
  ],
  subagents: [{ agent_id: "a2", agent_version_id: "v2" }],
  external_agents: [{ external_agent_id: "x1" }],
  max_steps: 20,
  reviewers: [
    { name: "Tone", model_profile_id: "p2", instructions: "Be kind", every: 5, window: 5 },
  ],
  code_mode: { enabled: true, max_tool_calls: 30 },
  budget: { monthly_usd: 5 },
  speech_to_text: {
    provider: "openai",
    model: "whisper-1",
    language: null,
    secret_id: "k1",
    dictation: true,
  },
  voice: {
    provider: "openai",
    model: "gpt-realtime",
    deployment: null,
    base_model: null,
    secret_id: "k1",
    voice: null,
    language: null,
    max_call_seconds: null,
    voice_note: null,
  },
};

describe("forSystemAgent", () => {
  it("drops every part a system agent's save refuses", () => {
    const stripped = forSystemAgent(STORED);

    expect(stripped.capabilities).toEqual([
      binding("thinking", { config: { effort: "high" } }),
      binding("context"),
      binding("skills"),
      binding("knowledge", { config: { top_k: 4 } }),
    ]);
    expect(stripped).toMatchObject({
      collection_ids: [],
      mcp_servers: [],
      subagents: [],
      external_agents: [],
      starters: [],
      reviewers: [],
      voice: null,
      speech_to_text: null,
      code_mode: { enabled: false, max_tool_calls: 30 },
    });
  });

  it("keeps a knowledge search without collections, which the platform picks for each run", () => {
    const stripped = forSystemAgent(STORED);

    expect(stripped.capabilities.find((entry) => entry.id === "knowledge")).toEqual(
      binding("knowledge", { config: { top_k: 4 } }),
    );
    expect(stripped.collection_ids).toEqual([]);
  });

  it("keeps a step count its publish refuses, for the refusal to name", () => {
    expect(forSystemAgent({ ...STORED, max_steps: 9 }).max_steps).toBe(9);
    expect(forSystemAgent({ ...STORED, max_steps: null }).max_steps).toBeNull();
  });

  it("keeps what a system agent works by", () => {
    const stripped = forSystemAgent(STORED);

    expect(stripped).toMatchObject({
      name: "Refunds judge",
      instructions: "Grade the answer.",
      model_profile_id: "p1",
      model_settings: { temperature: 0 },
      skill_ids: ["s1"],
      context_ids: ["c1"],
      max_steps: 20,
      budget: { monthly_usd: 5 },
    });
    expect(STORED.starters).toEqual(["Grade this"]);
  });

  it("adds no field the spec left out, so a clean one serializes as it came", () => {
    const clean: AgentSpec = {
      name: "Judge",
      instructions: "Grade.",
      model_settings: {},
      capabilities: [binding("thinking")],
      collection_ids: [],
      skill_ids: [],
      context_ids: [],
      mcp_servers: [],
    };

    expect(JSON.stringify(forSystemAgent(clean))).toBe(JSON.stringify(clean));
  });
});
