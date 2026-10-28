"use client";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { cn } from "@/lib/utils";
import type { ConversationAgent } from "@/types";
import { useTranslations } from "next-intl";

/** Beyond this the stack is a smudge; the rest are counted instead. */
const MAX_SHOWN = 3;

/**
 * How far each face after the first tucks under the one before it, by how many
 * share the stack - two overlap a little, three a lot, so a row of three faces
 * takes about the room of two - and how far they stand apart once the stack is
 * pointed at, so every face can be seen whole.
 */
const TUCK = { two: "-ml-1.5", more: "-ml-3.5" } as const;
const SPREAD = "group-hover/stack:ml-0.5";

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
  unframed = true,
  className,
}: {
  agents: ConversationAgent[] | undefined;
  size?: "sm" | "md";
  /** Off where the row is tight and the pictures carry it alone. */
  showName?: boolean;
  unframed?: boolean;
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
      <span className="group/stack flex shrink-0">
        {shown.map((agent, index) => (
          <AgentAvatar
            key={agent.id}
            agentId={agent.id}
            slug={agent.slug}
            hasAvatar={agent.has_avatar}
            colorSlot={agent.avatar_color}
            size={size}
            unframed={unframed}
            className={cn(
              "transition-[margin] duration-200 ease-out motion-reduce:transition-none",
              !unframed && "ring-background ring-2",
              index > 0 && [shown.length > 2 ? TUCK.more : TUCK.two, SPREAD],
            )}
          />
        ))}
      </span>
      {showName && (
        <span className="text-muted-foreground min-w-0 truncate text-xs">
          {agents.length === 1 ? agents[0]!.name : t("agentCount", { count: agents.length })}
        </span>
      )}
      {!showName && extra > 0 && <span className="text-muted-foreground text-xs">+{extra}</span>}
    </span>
  );
}
