"use client";

import { BookOpen, Database, FileText, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { cn } from "@/lib/utils";
import type { Mentionable } from "@/types/mention";

/** The mark a mention carries: the server's logo, the agent's face, or what kind of thing it is. */
export function MentionMark({ item, className }: { item: Mentionable; className?: string }) {
  const size = cn("h-4 w-4 shrink-0", className);
  if (item.kind === "mcp")
    return <McpServerIcon icon={item.icon} name={item.name} className={size} />;
  if (item.kind === "agent")
    return (
      <AgentAvatar
        agentId={item.id}
        slug={item.slug ?? item.name}
        hasAvatar={item.has_avatar}
        colorSlot={item.avatar_color}
        size="sm"
        className="h-4 w-4 text-[8px]"
      />
    );
  const Icon = item.kind === "collection" ? Database : item.kind === "skill" ? BookOpen : FileText;
  return <Icon className={cn(size, "text-muted-foreground")} aria-hidden />;
}

/**
 * One mention, as the composer holds it and the transcript shows it: a chip,
 * not text, because it carries what was picked rather than a name that only
 * reads like one.
 */
export function MentionChip({
  item,
  onRemove,
}: {
  item: Mentionable;
  /** Offered in the composer; the transcript's chips are fixed. */
  onRemove?: () => void;
}) {
  const t = useTranslations("chat.mentions");
  return (
    <span
      className="bg-foreground/[0.06] text-foreground inline-flex h-7 max-w-56 items-center gap-1.5 rounded-full pr-1 pl-2 text-xs font-medium"
      title={item.detail ?? item.name}
    >
      <MentionMark item={item} />
      <span className="truncate">{item.name}</span>
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          aria-label={t("remove", { name: item.name })}
          className="text-muted-foreground hover:text-foreground rounded-full p-0.5"
        >
          <X className="h-3 w-3" aria-hidden />
        </button>
      ) : (
        <span className="w-1" aria-hidden />
      )}
    </span>
  );
}
