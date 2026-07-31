/**
 * Edits to an agent spec that more than one control has to agree on.
 *
 * Kept out of the Builder page because each of these is a rule about the spec
 * rather than about a form: three separate controls now switch capabilities on
 * and off, and a binding assembled slightly differently by one of them is a
 * binding the server validates slightly differently.
 */

import type { AgentSpec, CapabilityBindingSpec, NotificationSpec } from "@/types/agents";

/** The capability that turns bound skills into tools the model can call. */
export const SKILLS_ID = "skills";

/**
 * The alert block an agent has when nothing has said otherwise.
 *
 * Mirrors the defaults in `backend/app/agents/spec.py`, and exists for the one
 * case where the client has to know them: an agent created in this session has
 * not been round-tripped through the API yet, so its spec carries no block at
 * all. Rendering "nothing is set" for an agent that will in fact mail the admins
 * would be the wrong answer to the only question this panel asks.
 *
 * The server is still the authority. This is never sent on its own - it is what
 * the form starts from, and what it saves is whatever the form then holds.
 */
export const DEFAULT_NOTIFICATIONS: NotificationSpec = {
  budget: { enabled: true, to: ["admins", "owner"], user_ids: [] },
  approvals: { enabled: true, to: ["initiator", "admins"], user_ids: [] },
  usage: { enabled: false, to: ["admins", "owner"], user_ids: [] },
};

/** The capability configured with the model settings - it contributes no tools. */
export const THINKING_ID = "thinking";

/**
 * The bindings with one capability switched on or off.
 *
 * Switching one on that is already on returns the list untouched, so a caller
 * cannot reset somebody's configuration by asking for a state it is already in.
 */
export function withCapability(
  bindings: CapabilityBindingSpec[],
  capabilityId: string,
  on: boolean,
): CapabilityBindingSpec[] {
  if (!on) return bindings.filter((binding) => binding.id !== capabilityId);
  if (bindings.some((binding) => binding.id === capabilityId)) return bindings;
  return [
    ...bindings,
    {
      id: capabilityId,
      config: {},
      approval: "default",
      tool_approval: {},
      tool_overrides: {},
      // Nothing chosen yet, which is what the settings say out loud for a
      // capability that needs one: it is the state publishing refuses, and it
      // is reached by switching the capability on.
      secret_id: null,
      enabled: true,
    },
  ];
}

/**
 * Bind skills, and the capability that can read them, as one decision.
 *
 * `skill_ids` resolves the skills into the run's resources; the `skills`
 * capability is what turns them into tools the model can call. Bound without
 * it, the skills were fetched and then thrown away - an agent that silently
 * knew nothing, with nothing anywhere saying why. Nobody wants one half of
 * this, so one function owns both.
 */
export function withSkills(spec: AgentSpec, skillIds: string[]): Partial<AgentSpec> {
  return {
    skill_ids: skillIds,
    capabilities: withCapability(spec.capabilities, SKILLS_ID, skillIds.length > 0),
  };
}
