import { ApiError } from "@/lib/api-error";
import { SANDBOX_ID, SUBAGENTS_ID } from "@/lib/agent-spec";
import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";

/**
 * The fixes a publish refusal can offer, by the code `validate_spec` names in
 * `details.fixes`.
 *
 * - `use_state_workspace`: the workspace becomes the stored one, which needs no
 *   sandbox connection.
 * - `stop_sharing_unbound`: delegates stop inheriting what this agent cannot
 *   share - a capability it no longer holds, and delegation itself.
 */
export const SPEC_FIXES = ["use_state_workspace", "stop_sharing_unbound"] as const;

export type SpecFix = (typeof SPEC_FIXES)[number];

/** The fixes a refusal offers that this console knows how to apply. A code it does not know is dropped. */
export function specFixes(error: unknown): SpecFix[] {
  if (!(error instanceof ApiError)) return [];
  const fixes = error.details?.fixes;
  if (!Array.isArray(fixes)) return [];
  return SPEC_FIXES.filter((fix) => fixes.includes(fix));
}

/**
 * The spec with one fix applied, ready to save as the draft.
 *
 * Both fixes leave the share list holding only what this agent can share, so
 * switching the workspace never leaves a second refusal behind it.
 */
export function applySpecFix(spec: AgentSpec, fix: SpecFix): AgentSpec {
  const capabilities =
    fix === "use_state_workspace" ? spec.capabilities.map(storedWorkspace) : spec.capabilities;
  return { ...spec, capabilities: withoutUnshareable(capabilities) };
}

/** As the workspace section switches it: a runtime and a connection mean nothing without a container. */
function storedWorkspace(binding: CapabilityBindingSpec): CapabilityBindingSpec {
  if (binding.id !== SANDBOX_ID) return binding;
  return {
    ...binding,
    config: { ...binding.config, backend: "state", runtime: null, connection_id: null },
  };
}

function withoutUnshareable(capabilities: CapabilityBindingSpec[]): CapabilityBindingSpec[] {
  const held = new Set(capabilities.filter((binding) => binding.enabled).map(({ id }) => id));
  return capabilities.map((binding) => {
    const shared = binding.config.share_with_delegates;
    if (binding.id !== SUBAGENTS_ID || !Array.isArray(shared)) return binding;
    return {
      ...binding,
      config: {
        ...binding.config,
        share_with_delegates: shared.filter((id) => held.has(id) && id !== SUBAGENTS_ID),
      },
    };
  });
}
