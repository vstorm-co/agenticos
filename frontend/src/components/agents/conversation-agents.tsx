"use client";

import { BrandIcon } from "@/components/icons/brand-icon";
import { useConversationAgentLabel } from "@/hooks/use-conversation-agent-label";
import type { CodingHarness } from "@/types/chat";
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
const TUCK = {
  sm: { two: "-ml-3 group-hover/stack:-ml-2", more: "-ml-4 group-hover/stack:-ml-3" },
  md: { two: "-ml-5 group-hover/stack:-ml-4", more: "-ml-6 group-hover/stack:-ml-5" },
} as const;

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
  codingAgents = [],
  size = "sm",
  showName = true,
  unframed = true,
  className,
  compact = false,
}: {
  agents: ConversationAgent[] | undefined;
  codingAgents?: CodingHarness[];
  size?: "sm" | "md";
  /** Off where the row is tight and the pictures carry it alone. */
  showName?: boolean;
  unframed?: boolean;
  className?: string;
  /** Fixed-width rail: overlap faces without spreading beyond the row on hover. */
  compact?: boolean;
}) {
  const tHarness = useTranslations("chat.localAgent");
  const platform = agents ?? [];
  const label = useConversationAgentLabel(platform, codingAgents);
  type Face =
    { kind: "agent"; agent: ConversationAgent } | { kind: "coding"; harness: CodingHarness };
  const all: Face[] = platform.map((agent) => ({ kind: "agent", agent }));
  all.splice(
    Math.min(1, all.length),
    0,
    ...codingAgents.map((harness): Face => ({ kind: "coding", harness })),
  );
  if (all.length === 0) return null;
  const shown = all.slice(0, MAX_SHOWN);
  const extra = all.length - shown.length;
  const compactTuck = size === "md" ? (shown.length > 2 ? "-ml-[34px]" : "-ml-8") : "-ml-5";

  return (
    <span
      className={cn("relative inline-flex min-w-0 items-center gap-1.5", className)}
      title={[
        ...platform.map((agent) => agent.name),
        ...codingAgents.map((harness) => tHarness(harness === "codex" ? "codex" : "claudeCode")),
      ].join(" → ")}
    >
      <span className="group/stack flex shrink-0">
        {shown.map((face, index) => {
          const stack = cn(
            "transition-[margin] duration-200 ease-out motion-reduce:transition-none",
            !unframed && "ring-background ring-2",
            ["relative z-30", "relative z-20", "relative z-10"][index],
            index > 0 &&
              (compact ? compactTuck : shown.length > 2 ? TUCK[size].more : TUCK[size].two),
          );
          return face.kind === "agent" ? (
            <AgentAvatar
              key={face.agent.id}
              agentId={face.agent.id}
              slug={face.agent.slug}
              hasAvatar={face.agent.has_avatar}
              colorSlot={face.agent.avatar_color}
              size={size}
              unframed={unframed}
              className={stack}
            />
          ) : (
            <span
              key={face.harness}
              role="img"
              aria-label={tHarness(face.harness === "codex" ? "codex" : "claudeCode")}
              className={cn(
                stack,
                "bg-background border-foreground/10 flex shrink-0 items-center justify-center rounded-full border",
                size === "md" ? "size-9" : "size-6",
              )}
            >
              <BrandIcon
                name={face.harness === "codex" ? "codex" : "claude_code"}
                className={size === "md" ? "size-4" : "size-3.5"}
              />
            </span>
          );
        })}
      </span>
      {showName && <span className="text-muted-foreground min-w-0 truncate text-xs">{label}</span>}
      {!showName && !compact && extra > 0 && (
        <span className="text-muted-foreground text-xs">+{extra}</span>
      )}
    </span>
  );
}
