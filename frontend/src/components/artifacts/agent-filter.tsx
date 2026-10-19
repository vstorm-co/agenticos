"use client";

import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
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
            <span className="flex min-w-0 items-center gap-2">
              {/* Hidden from the accessible name, which is the agent's name alone. */}
              <span aria-hidden>
                <AgentAvatar
                  agentId={agent.id}
                  slug={agent.slug}
                  hasAvatar={agent.has_avatar}
                  colorSlot={agent.avatar_color}
                  size="sm"
                  className="h-5 w-5"
                />
              </span>
              <span className="truncate">{agent.name}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
