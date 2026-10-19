"use client";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { BrandIcon } from "@/components/icons/brand-icon";
import type { DelegateRef } from "@/lib/delegations";
import { cn } from "@/lib/utils";

/**
 * Who a delegation went to, by face: the agent's own avatar, or the mark of the
 * coding harness - Claude Code, Codex - that the `coding_agent` capability ran.
 *
 * A harness pulses while it works, as an agent's face thinks.
 */
export function DelegateFace({
  who,
  thinking = false,
  className,
}: {
  who: DelegateRef;
  thinking?: boolean;
  className?: string;
}) {
  if (who.harness !== undefined) {
    return (
      <span
        role="img"
        aria-label={who.name}
        className={cn(
          "bg-foreground text-background grid shrink-0 place-items-center rounded-full",
          thinking && "animate-pulse",
          className,
        )}
      >
        <BrandIcon name={who.harness} className="size-[60%]" aria-hidden />
      </span>
    );
  }
  return (
    <AgentAvatar
      agentId={who.id ?? who.slug}
      slug={who.slug}
      hasAvatar={who.has_avatar}
      colorSlot={who.avatar_color}
      size="sm"
      thinking={thinking}
      className={className}
    />
  );
}
