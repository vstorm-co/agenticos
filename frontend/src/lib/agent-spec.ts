/**
 * Edits to an agent spec that more than one control has to agree on.
 *
 * Kept out of the Builder page because each of these is a rule about the spec
 * rather than about a form: three separate controls now switch capabilities on
 * and off, and a binding assembled slightly differently by one of them is a
 * binding the server validates slightly differently.
 */

import type { FieldProblem } from "@/lib/api-error";
import type {
  AgentSpec,
  AgentVersion,
  CapabilityBindingSpec,
  NotificationSpec,
  SpecialistSpec,
  SubagentRef,
  SubagentsConfig,
} from "@/types/agents";

/** The capability that turns bound skills into tools the model can call. */
export const SKILLS_ID = "skills";

/** The capability that searches the collections bound in `collection_ids`. */
export const KNOWLEDGE_ID = "knowledge";

/**
 * The binding a capability would get if somebody switched it on.
 *
 * So the detail panel has something to render for a capability nobody has
 * granted yet: its controls are shown at their real values and left inert, and
 * the switch that grants it is on the panel too. Deliberately the same shape
 * `withCapability` creates, and deliberately never passed to a change handler -
 * it is what the panel *would* be configuring, shown so the decision can be made
 * on the real thing rather than on an abridgement.
 */
export function unboundBinding(capabilityId: string): CapabilityBindingSpec {
  return {
    id: capabilityId,
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: false,
  };
}

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
 * The workspace capability, which has a section of its own.
 *
 * Every other capability answers "may this agent do X". This one answers "where
 * does it keep things, and who else can read them" - four choices with
 * different infrastructure behind them, one of which shares files between
 * people. A row in the capability picker would present that as the same kind of
 * decision as switching on a chart tool.
 */
export const SANDBOX_ID = "sandbox";

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
export function withSkills(
  // Widened from `AgentSpec` to what this actually reads, so an inline
  // specialist - which binds skills and the capability that reads them exactly
  // as an agent does - gets the same rule rather than a second copy of it.
  spec: { capabilities: CapabilityBindingSpec[] },
  skillIds: string[],
): Pick<AgentSpec, "skill_ids" | "capabilities"> {
  return {
    skill_ids: skillIds,
    capabilities: withCapability(spec.capabilities, SKILLS_ID, skillIds.length > 0),
  };
}

/** The capability that injects bound context files and exposes the linked ones. */
export const CONTEXT_ID = "context";

/**
 * Bind context files, and the capability that reaches them, as one decision.
 *
 * `context_ids` resolves the files into the run's resources; the `context`
 * capability is what injects the `inject`-mode ones and exposes a read tool for
 * the `link`-mode ones. Bound without it, the files were fetched and discarded -
 * the same silent half a skill binding avoids - so one function owns both. The
 * mode lives on each file, not here, so switching the capability on covers both.
 */
export function withContextFiles(
  spec: { capabilities: CapabilityBindingSpec[] },
  contextIds: string[],
): Pick<AgentSpec, "context_ids" | "capabilities"> {
  return {
    context_ids: contextIds,
    capabilities: withCapability(spec.capabilities, CONTEXT_ID, contextIds.length > 0),
  };
}

/**
 * The delegation capability, which has a section of its own.
 *
 * Its configuration is three unrelated things - a list of published agents
 * pinned to versions, a list of specialists that are not versioned at all, and
 * the policy bounding both - and only the third is a set of fields a generated
 * form can render.
 */
export const SUBAGENTS_ID = "subagents";

/** What the delegation capability does when nothing has said otherwise. */
export const DEFAULT_SUBAGENTS_CONFIG: SubagentsConfig = {
  inline: [],
  mode: "sync",
  allow_dynamic: false,
  max_depth: 1,
  max_fanout: 3,
  max_result_chars: 2000,
  share_with_delegates: [],
};

/**
 * A binding's config as delegation reads it, with the shipped defaults filled in.
 *
 * Mirrors `SubagentsConfig` in `backend/app/agents/capabilities/subagents/`, and
 * exists for the one case the server cannot cover: a binding switched on in this
 * session carries `{}`, and rendering "no specialists, depth 0, no mode" for an
 * agent that will in fact delegate once, synchronously, is the wrong answer to
 * every question the panel asks.
 */
export function readSubagentsConfig(binding: CapabilityBindingSpec | undefined): SubagentsConfig {
  return { ...DEFAULT_SUBAGENTS_CONFIG, ...(binding?.config as Partial<SubagentsConfig>) };
}

/** A specialist with nothing filled in, which is what "add one" produces. */
export function newSpecialist(): SpecialistSpec {
  return {
    name: "",
    description: "",
    instructions: "",
    model_profile_id: null,
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    context_ids: [],
    max_steps: null,
    preferred_mode: null,
  };
}

/** What the parent's model may address a specialist by - it becomes a tool argument. */
const SPECIALIST_NAME_PATTERN = /^[a-zA-Z0-9_-]+$/;

/**
 * Why this specialist name will not do, as a catalog key, or null when it will.
 *
 * A key rather than a sentence, for the reason `toolNameError` is: this is a pure
 * function called from a form field and from its own tests, and threading a
 * translator through it would put the words further from the catalog.
 */
export function specialistNameError(name: string): string | null {
  if (name.length === 0) return "specialistNameBlank";
  if (name.length > 64) return "specialistNameTooLong";
  if (!SPECIALIST_NAME_PATTERN.test(name)) return "specialistNamePattern";
  return null;
}

/**
 * Names claimed more than once across the delegates and the specialists.
 *
 * The parent's model addresses every subagent by name, so two things answering
 * to one name means the model cannot say which it meant and the second shadows
 * the first. Publishing refuses it; saying so here is what stops somebody
 * finding out from a failed publish half an hour later.
 *
 * Delegate names are the delegates' own handles - an agent's slug, which is what
 * the runtime resolves a `SubagentRef` to.
 */
export function delegationNameClashes(
  delegateNames: readonly string[],
  specialists: readonly SpecialistSpec[],
): Set<string> {
  const seen = new Set<string>();
  const clashes = new Set<string>();
  for (const name of [...delegateNames, ...specialists.map((entry) => entry.name)]) {
    if (name === "") continue;
    if (seen.has(name)) clashes.add(name);
    seen.add(name);
  }
  return clashes;
}

/** Agents pinned more than once, which the spec's own validator refuses. */
export function duplicateDelegateIds(subagents: readonly SubagentRef[]): Set<string> {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const ref of subagents) {
    if (seen.has(ref.agent_id)) duplicates.add(ref.agent_id);
    seen.add(ref.agent_id);
  }
  return duplicates;
}

/**
 * How a pin stands against the delegate's own history.
 *
 * `gone` is the one worth spelling out: a pin whose version no longer exists
 * fails the run, loudly, naming the delegate - never a quiet fall back to the
 * current version, because the reason to pin is that nothing changes without a
 * decision.
 */
export type PinStatus =
  | { kind: "unknown" }
  | { kind: "current"; version: number }
  | { kind: "behind"; version: number; latest: number; by: number }
  | { kind: "gone" };

/**
 * How many versions the history holds at most.
 *
 * `list_versions` in `backend/app/repositories/agent.py` takes `limit: int = 50`
 * and the route passes no override, so a pin older than fifty publishes is
 * absent from a history that is nonetheless complete as far as it goes. It reads
 * as `unknown` rather than as `gone`: "this version was deleted" and "this
 * version is off the end of the page I could read" have different fixes, and
 * only one of them is true.
 */
export const VERSION_HISTORY_LIMIT = 50;

/**
 * Where a pinned version sits relative to what the delegate publishes now.
 *
 * Reads the agent's `current_version_id` rather than the highest number in the
 * list, because that is what a run of the unpinned agent would use - a rollback
 * publishes a new version rather than moving the pointer back, so the two agree,
 * and trusting the pointer means this keeps telling the truth if they ever stop
 * agreeing.
 */
export function pinStatus(
  versions: readonly AgentVersion[],
  pinnedVersionId: string,
  currentVersionId: string | null,
): PinStatus {
  // Before anything is looked up. An empty history is a request in flight or one
  // that was refused, and every published agent has at least one version - so
  // reading it as "the pinned version is gone" would flash the worst verdict
  // this function has onto every row on every load.
  if (versions.length === 0) return { kind: "unknown" };
  const pinned = versions.find((version) => version.id === pinnedVersionId);
  if (pinned === undefined) {
    return versions.length >= VERSION_HISTORY_LIMIT ? { kind: "unknown" } : { kind: "gone" };
  }
  if (pinned.id === currentVersionId) return { kind: "current", version: pinned.version };
  const current = versions.find((version) => version.id === currentVersionId);
  if (current === undefined) return { kind: "unknown" };
  return {
    kind: "behind",
    version: pinned.version,
    latest: current.version,
    by: current.version - pinned.version,
  };
}

/**
 * What publish validation said about one capability's configuration form.
 *
 * `validate_spec` reports every problem in a spec at once, so its `fields`
 * arrive as one flat list of paths, and the path is what says which of the
 * forms on the page a field name belongs to. Two things follow from matching
 * the whole prefix rather than the leaf. A `default_top_k` refused on one
 * capability is not marked on every other card that has one. And a capability
 * configured inside a delegate is reported under
 * `specialists.researcher.capabilities.…`, which is not this card either - the
 * Builder renders one form per specialist, and they configure the same
 * capabilities as their parent.
 *
 * Empty for a capability nothing was said about, which is the ordinary case -
 * most publish problems are broken references with no input to mark at all.
 */
export function capabilityConfigErrors(
  problems: readonly FieldProblem[],
  capabilityId: string,
): Readonly<Record<string, string>> {
  const prefix = `capabilities.${capabilityId}.config.`;
  const errors: Record<string, string> = {};
  for (const problem of problems) {
    if (!problem.field.startsWith(prefix)) continue;
    errors[problem.field.slice(prefix.length)] = problem.message;
  }
  return errors;
}
