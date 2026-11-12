import type { Translate } from "@/lib/agent-step-captions";
import type { SkillAgentUsage, SkillBinding } from "@/types/skill-versions";

/** What an agent's binding reads as: `v7 · pinned · 3 behind main`. */
export function bindingLabel(t: Translate, binding: SkillBinding): string {
  const { number } = binding.version;
  if (binding.state === "main") return t("state.main", { number });
  if (binding.state === "pinned") return t("state.pinned", { number, behind: binding.behind_main });
  return t("state.fork", {
    name: binding.fork?.name ?? "",
    base: binding.fork?.base_number ?? 0,
    changes: binding.fork?.changes ?? 0,
    behind: binding.behind_main,
  });
}

/**
 * What the agents table shows: everyone, one state, one fork's agents, or the agents
 * bound only in a draft, which follow no line.
 *
 * Kept in the address as `?show=`, so a fork's agents are a link to send. A fork
 * is `fork:<id>`; anything unknown reads as everyone.
 */
export type ShownAgents = "all" | "main" | "pinned" | "draft" | `fork:${string}`;

export function shownAgents(param: string | null): ShownAgents {
  if (param === "main" || param === "pinned" || param === "draft") return param;
  if (param?.startsWith("fork:") && param.length > "fork:".length) return param as ShownAgents;
  return "all";
}

/** The line a shown choice edits and lists the history of: a fork's id, or null for main. */
export function lineOf(shown: ShownAgents): string | null {
  return shown.startsWith("fork:") ? shown.slice("fork:".length) : null;
}

/** Whether an agent belongs to the shown choice. Draft-only agents belong to no line. */
export function isShown(usage: SkillAgentUsage, shown: ShownAgents): boolean {
  if (shown === "all") return true;
  if (shown === "draft") return usage.draft_only;
  if (usage.draft_only) return false;
  if (shown === "main" || shown === "pinned") return usage.binding.state === shown;
  return usage.binding.fork?.id === lineOf(shown);
}

/**
 * One row of the agents list. An agent and each of its inline specialists read a
 * skill their own way, so one agent can have several rows.
 */
export function readerKey(usage: SkillAgentUsage): string {
  return `${usage.agent.id}:${usage.via_specialist ?? ""}`;
}

/** The rows' agents, each once: the first row of an agent stands for it. */
export function eachAgentOnce(rows: SkillAgentUsage[]): SkillAgentUsage[] {
  return rows.filter(
    (usage, index) => rows.findIndex((other) => other.agent.id === usage.agent.id) === index,
  );
}

/**
 * Whether the agent's answers never used another version than the one it serves:
 * no change has reached it, so a version no check measured is simply not checked yet.
 */
export function neverMoved(usage: SkillAgentUsage): boolean {
  return (usage.answered_with ?? []).every((id) => id === usage.binding.version.id);
}
