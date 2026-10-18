"use client";

import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAgents } from "@/hooks";
import { useAssistant } from "@/hooks/use-assistant";

/** The sentinel a Radix select needs for "no value" - it refuses an empty string. */
const NONE = "none";

/**
 * The agent a new chat in the project starts with.
 *
 * Only agents the reader may run and that are published: a default nobody can
 * start a chat with is a project whose New chat button fails. Any agent can
 * still answer in the project - this is where a chat starts, not a lock.
 */
export function DefaultAgentSelect({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: string | null;
  onChange: (agentId: string | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("projects");
  const { agents } = useAgents();
  // The organization's assistant, once switched off, answers no chat - and the
  // listing says nothing of it, so the assistant's own state does.
  const { assistant } = useAssistant();
  const switchedOff = assistant?.status === "disabled" ? assistant.agent_id : null;
  const runnable = agents.filter(
    (agent) =>
      agent.can_run &&
      agent.current_version_id !== null &&
      agent.status !== "archived" &&
      agent.id !== switchedOff,
  );
  return (
    <Select
      value={value ?? NONE}
      onValueChange={(next) => onChange(next === NONE ? null : next)}
      disabled={disabled}
    >
      <SelectTrigger id={id}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>{t("noDefaultAgent")}</SelectItem>
        {runnable.map((agent) => (
          <SelectItem key={agent.id} value={agent.id}>
            <span className="flex items-center gap-2">
              <AgentAvatar
                agentId={agent.id}
                slug={agent.slug}
                hasAvatar={agent.has_avatar}
                colorSlot={agent.avatar_color}
                size="sm"
              />
              {agent.name}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
