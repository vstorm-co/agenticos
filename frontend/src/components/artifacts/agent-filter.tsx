"use client";

import { useTranslations } from "next-intl";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import type { ArtifactAgent } from "@/types/artifact";

/** Stands for "every agent" in the select, which an agent id never is. */
const EVERY = "every";

interface AgentFilterProps {
  /** The publishers of what the caller can see, as the server named them. */
  agents: ArtifactAgent[];
  /** The agent the list is narrowed to, or null for all of them. */
  value: string | null;
  onChange: (agentId: string | null) => void;
}

/**
 * Narrow the list to one agent's pages.
 *
 * Nothing to choose between with one publisher, so the control appears only
 * once there are two - or while a filter is on, so it can be taken off again.
 */
export function AgentFilter({ agents, value, onChange }: AgentFilterProps) {
  const t = useTranslations("artifacts");
  if (agents.length < 2 && value === null) return null;
  return (
    <Select value={value ?? EVERY} onValueChange={(next) => onChange(next === EVERY ? null : next)}>
      <SelectTrigger className="w-full sm:w-48" aria-label={t("filterByAgent")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={EVERY}>{t("everyAgent")}</SelectItem>
        {agents.map((agent) => (
          <SelectItem key={agent.id} value={agent.id}>
            {agent.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
