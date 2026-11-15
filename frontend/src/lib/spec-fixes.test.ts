import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-error";
import { applySpecFix, specFixes } from "@/lib/spec-fixes";
import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";

function binding(
  id: string,
  config: Record<string, unknown> = {},
  enabled = true,
): CapabilityBindingSpec {
  return {
    id,
    config,
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled,
  };
}

function spec(capabilities: CapabilityBindingSpec[]): AgentSpec {
  return {
    spec_version: 5,
    name: "Support",
    description: null,
    instructions: "",
    model_profile_id: null,
    model_settings: {},
    capabilities,
    collection_ids: [],
    skill_ids: [],
    context_ids: [],
    mcp_servers: [],
    budget: null,
  };
}

function refusal(details: Record<string, unknown>): ApiError {
  return new ApiError(400, "This agent cannot be published yet", {
    error: { code: "BAD_REQUEST", message: "This agent cannot be published yet", details },
  });
}

const byId = (fixed: AgentSpec, id: string) => fixed.capabilities.find((b) => b.id === id)?.config;

describe("specFixes", () => {
  it("reads the fixes a refusal offers, dropping a code this console does not know", () => {
    const error = refusal({
      problems: ["..."],
      fixes: ["stop_sharing_unbound", "reticulate_splines", "use_state_workspace"],
    });

    expect(specFixes(error)).toEqual(["use_state_workspace", "stop_sharing_unbound"]);
  });

  it("offers nothing for a refusal without fixes, or a failure that is not a refusal", () => {
    expect(specFixes(refusal({ problems: ["..."] }))).toEqual([]);
    expect(specFixes(refusal({ fixes: "use_state_workspace" }))).toEqual([]);
    expect(specFixes(new Error("offline"))).toEqual([]);
  });
});

describe("applySpecFix", () => {
  it("puts the workspace on the stored backend, without a runtime or a connection", () => {
    const fixed = applySpecFix(
      spec([
        binding("sandbox", {
          backend: "service",
          runtime: "python",
          connection_id: "c-1",
          session_scope: "user",
        }),
      ]),
      "use_state_workspace",
    );

    expect(byId(fixed, "sandbox")).toEqual({
      backend: "state",
      runtime: null,
      connection_id: null,
      session_scope: "user",
    });
  });

  it("leaves the share list holding only what the agent can share, whichever fix", () => {
    const capabilities = [
      binding("sandbox", { backend: "service" }),
      binding("charts", {}, false),
      binding("subagents", {
        max_depth: 2,
        share_with_delegates: ["sandbox", "charts", "subagents"],
      }),
    ];

    for (const fix of ["use_state_workspace", "stop_sharing_unbound"] as const) {
      expect(byId(applySpecFix(spec(capabilities), fix), "subagents")).toEqual({
        max_depth: 2,
        share_with_delegates: ["sandbox"],
      });
    }
  });

  it("stops sharing without touching the workspace or anything else", () => {
    const sandbox = binding("sandbox", { backend: "service", runtime: "python" });
    const subagents = binding("subagents", { mode: "sync" });

    const fixed = applySpecFix(spec([sandbox, subagents]), "stop_sharing_unbound");

    expect(fixed.capabilities).toEqual([sandbox, subagents]);
  });
});
