"use client";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { cn } from "@/lib/utils";
import type { ConversationAgent } from "@/types";
import { useTranslations } from "next-intl";

/** Beyond this the stack is a smudge; the rest are counted instead. */
const MAX_SHOWN = 3;

/**
 * Who answered in a conversation, as a list view shows it.
 *
 * Plural on purpose. A conversation is not had with one agent - the picker can
 * be changed mid-thread - so the answer to "which agent is this" is sometimes
 * two of them, and naming only the last would be a quiet lie about the first
 * half of the transcript.
 *
 * Nothing renders when no agent took part: that is the general assistant, and a
 * badge saying so on every row would be noise on the common case.
 */
export function ConversationAgents({
  agents,
  size = "sm",
  showName = true,
  className,
}: {
  agents: ConversationAgent[] | undefined;
  size?: "sm" | "md";
  /** Off where the row is tight and the pictures carry it alone. */
  showName?: boolean;
  className?: string;
}) {
  const t = useTranslations("agents");
  if (!agents || agents.length === 0) return null;

  const shown = agents.slice(0, MAX_SHOWN);
  const extra = agents.length - shown.length;

  return (
    <span
      className={cn("inline-flex min-w-0 items-center gap-1.5", className)}
      title={agents.map((agent) => agent.name).join(" → ")}
    >
      <span className="flex shrink-0 -space-x-1.5">
        {shown.map((agent) => (
          <AgentAvatar
            key={agent.id}
            agentId={agent.id}
            name={agent.name}
            hasAvatar={agent.has_avatar}
            size={size}
            className="ring-background ring-2"
          />
        ))}
      </span>
      {showName && (
        <span className="text-muted-foreground min-w-0 truncate text-[11px]">
          {agents.length === 1 ? agents[0]!.name : t("agentCount", { count: agents.length })}
        </span>
      )}
      {!showName && extra > 0 && (
        <span className="text-muted-foreground text-[11px]">+{extra}</span>
      )}
    </span>
  );
}
