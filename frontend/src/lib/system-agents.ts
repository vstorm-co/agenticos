import type { AgentKind, SystemAgentKind } from "@/types/agents";

/**
 * Every kind of agent only the platform runs, in the order the agents catalog
 * lists them under System agents. A new kind is a row here, its
 * `agents.<kind>Kind` and `<kind>KindHint` copy, and nothing else.
 */
export const SYSTEM_AGENT_KINDS: readonly SystemAgentKind[] = [
  "judge",
  "drafter",
  "generator",
  "improver",
];

/** Whether only the platform runs an agent of this kind; an unknown kind is an ordinary agent. */
export function isSystemAgent(kind: AgentKind | undefined): boolean {
  return kind !== undefined && kind !== "agent";
}
