import { CONTEXT_ID, KNOWLEDGE_ID, SKILLS_ID, THINKING_ID } from "@/lib/agent-spec";
import type { AgentKind, AgentSpec, SystemAgentKind } from "@/types/agents";

/**
 * Every kind of agent only the platform runs, in the order the agents catalog
 * lists them under System agents. A new kind is a row here, its
 * `agents.<kind>Kind` and `<kind>KindHint` copy, and nothing else.
 */
export const SYSTEM_AGENT_KINDS: readonly SystemAgentKind[] = [
  "judge",
  "drafter",
  "generator",
  "classifier",
  "improver",
];

/** Whether only the platform runs an agent of this kind; an unknown kind is an ordinary agent. */
export function isSystemAgent(kind: AgentKind | undefined): kind is SystemAgentKind {
  return kind !== undefined && kind !== "agent";
}

/**
 * The capabilities a system agent may bind: how it reasons, the standing text it
 * reads, and a search of the knowledge bases the platform picks for each run -
 * never anything that reaches further than what the run is about. The backend's
 * `SYSTEM_CAPABILITIES` holds the same four.
 */
const SYSTEM_AGENT_CAPABILITIES: readonly string[] = [
  THINKING_ID,
  CONTEXT_ID,
  SKILLS_ID,
  KNOWLEDGE_ID,
];

/**
 * Whether a system agent of `kind` is offered the capability `capabilityId`: any
 * of the four it may bind, except skills for a classifier.
 */
export function systemAgentOffers(kind: SystemAgentKind, capabilityId: string): boolean {
  if (kind === "classifier" && capabilityId === SKILLS_ID) return false;
  return SYSTEM_AGENT_CAPABILITIES.includes(capabilityId);
}

/**
 * What a system agent may be given out of `items`: only what is shared with the
 * whole organization, since its publish refuses anything narrower - plus what it
 * already holds, so a pick made before that can still be taken off.
 *
 * `total` follows: a gallery names a chosen id it does not list as deleted only
 * while it holds the whole set, which the narrowed list still is when nothing was
 * left unfetched.
 */
export function sharedWithOrganization<T extends { id: string; visibility: string }>(
  items: T[],
  total: number,
  chosen: string[],
): { items: T[]; total: number } {
  const kept = items.filter((item) => item.visibility === "org" || chosen.includes(item.id));
  return { items: kept, total: items.length >= total ? kept.length : total };
}

/** The model requests a system agent that searches makes when `max_steps` is unset. */
export const SYSTEM_AGENT_SEARCH_STEPS = 3;

/** The most `max_steps` a system agent's publish accepts: each is paid for on every answer it reads. */
export const SYSTEM_AGENT_MAX_STEPS = 5;

/**
 * The kinds whose answer is a verdict - a judge's grade, a classifier's label -
 * which the same input should get every time it is asked.
 */
export type VerdictKind = Extract<SystemAgentKind, "judge" | "classifier">;

/** The verdict an agent of this kind gives, or undefined for one that drafts rather than decides. */
export function verdictKind(kind: AgentKind | undefined): VerdictKind | undefined {
  return kind === "judge" || kind === "classifier" ? kind : undefined;
}

/**
 * `spec` without what saving a system agent's draft refuses.
 *
 * Only the platform runs a system agent, so it reaches nothing beyond its prompt
 * and the knowledge bases of the run: no capability but thinking, context, skills
 * and knowledge - and those without approvals, since nobody is there to give one -
 * no knowledge base of its own, since the platform picks them for each run, no
 * MCP server or delegate, and none of a chat's starters, calls, dictation, code
 * mode or reviewers. A draft stored before those were refused can still hold
 * them, and its page no longer shows any of them to remove. `max_steps` stays as
 * it is: its save takes any value, and its publish refuses one above
 * `SYSTEM_AGENT_MAX_STEPS` and says why.
 *
 * A field the spec leaves out stays out, so a spec holding none of it serializes
 * exactly as it came.
 */
export function forSystemAgent(spec: AgentSpec): AgentSpec {
  const next: AgentSpec = {
    ...spec,
    capabilities: spec.capabilities
      .filter((binding) => SYSTEM_AGENT_CAPABILITIES.includes(binding.id))
      .map((binding) => ({ ...binding, approval: "default", tool_approval: {} })),
    collection_ids: [],
    mcp_servers: [],
  };
  if (spec.subagents !== undefined) next.subagents = [];
  if (spec.external_agents !== undefined) next.external_agents = [];
  if (spec.starters !== undefined) next.starters = [];
  if (spec.reviewers !== undefined) next.reviewers = [];
  if (spec.voice !== undefined) next.voice = null;
  if (spec.speech_to_text !== undefined) next.speech_to_text = null;
  if (spec.code_mode !== undefined) next.code_mode = { ...spec.code_mode, enabled: false };
  return next;
}
