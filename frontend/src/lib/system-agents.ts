import { CONTEXT_ID, SKILLS_ID, THINKING_ID } from "@/lib/agent-spec";
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
 * The capabilities a system agent may bind: how it reasons and what standing text
 * it knows, never anything it could call to reach further than its prompt. The
 * backend's `SYSTEM_CAPABILITIES` holds the same three.
 */
const SYSTEM_AGENT_CAPABILITIES: readonly string[] = [THINKING_ID, CONTEXT_ID, SKILLS_ID];

/**
 * `spec` without what saving a system agent's draft refuses.
 *
 * Only the platform runs a system agent, so it reaches nothing beyond its prompt:
 * no capability but thinking, context and skills - and those without approvals,
 * since nobody is there to give one - no knowledge base, MCP server or delegate,
 * and none of a chat's starters, calls, dictation, code mode or reviewers. A draft
 * stored before those were refused can still hold them, and its page no longer
 * shows any of them to remove.
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
