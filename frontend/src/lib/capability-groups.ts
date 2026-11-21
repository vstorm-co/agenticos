import type { CapabilityCatalogEntry } from "@/types/agents";

/** Product navigation, independent of the registry's execution categories. */
const GROUPS = [
  { name: "basics", ids: ["sandbox", "ask_user", "drafts", "clock", "code_execution"] },
  {
    name: "knowledge",
    ids: ["skills", "context", "memory_files", "knowledge", "conversation_search"],
  },
  { name: "research", ids: ["web_research", "web_fetch", "browser_use", "computer_use"] },
  {
    name: "outputs",
    ids: [
      "artifacts",
      "visuals",
      "charts",
      "image_generation",
      "text_to_speech",
      "video_generation",
      "mirage",
    ],
  },
  { name: "delegation", ids: ["subagents", "coding_agent", "external_acp"] },
  {
    name: "automation",
    ids: ["monitor", "background_tasks", "background_tools", "follow_ups", "workflows"],
  },
  { name: "channels", ids: ["phone_calls", "channel_actions", "channel_tools"] },
  {
    name: "advanced",
    ids: [
      "compaction",
      "tool_search",
      "tool_output_limits",
      "media",
      "system_reminders",
      "planning",
      "thinking",
      "guardrails",
    ],
  },
] as const;

export function capabilityGroups(catalog: CapabilityCatalogEntry[], enabled: ReadonlySet<string>) {
  const groupOf = (entry: CapabilityCatalogEntry): string =>
    GROUPS.find((group) => group.ids.some((id) => id === entry.id))?.name ?? entry.category;
  const order: readonly string[] = GROUPS.map((group) => group.name);
  const names = [...new Set(catalog.map(groupOf))].sort((a, b) => {
    const rank = (name: string) =>
      name === "advanced"
        ? Number.MAX_SAFE_INTEGER
        : order.includes(name)
          ? order.indexOf(name)
          : order.length;
    return rank(a) - rank(b) || a.localeCompare(b);
  });
  return names.map((name) => ({
    name,
    entries: catalog
      .filter((entry) => groupOf(entry) === name)
      .sort(
        (a, b) =>
          Number(enabled.has(b.id)) - Number(enabled.has(a.id)) ||
          Number(Boolean(b.recommended)) - Number(Boolean(a.recommended)) ||
          a.name.localeCompare(b.name),
      ),
  }));
}
