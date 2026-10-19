"use client";

import { BookOpen, Database, FileText, FolderKanban, Wrench } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { readableLink, richSegments } from "@/lib/rich-text";
import { CAPABILITY_HUE } from "@/components/agents/capability-art/art.generated";
import { STEP_ICONS } from "@/lib/step-icons";
import { toolEntry } from "@/lib/tool-catalog";
import { cn } from "@/lib/utils";
import type { Mentionable } from "@/types/mention";

import { LinkFavicon } from "./link-favicon";

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
        // The size the caller gives every mark, so a face sits as large as a
        // server's logo or a capability's tile beside it.
        className={cn("h-4 w-4 text-[8px]", className)}
      />
    );
  if (item.kind === "capability") {
    // The capability's own hue, as its Toolbox card has it, behind the icon of
    // what it does - one glance from the menu to the card it came from.
    const entry = item.icon ? toolEntry(item.icon) : null;
    const Icon = entry ? STEP_ICONS[entry.kind] : Wrench;
    const hue = CAPABILITY_HUE[item.id];
    return (
      <span
        className={cn(size, "grid place-items-center rounded-[4px]")}
        style={
          hue === undefined
            ? undefined
            : { background: `oklch(0.92 0.06 ${hue})`, color: `oklch(0.45 0.13 ${hue})` }
        }
        aria-hidden
      >
        <Icon className="h-[75%] w-[75%]" />
      </span>
    );
  }
  const Icon =
    item.kind === "collection"
      ? Database
      : item.kind === "skill"
        ? BookOpen
        : item.kind === "project"
          ? FolderKanban
          : FileText;
  return <Icon className={cn(size, "text-muted-foreground")} aria-hidden />;
}

/**
 * A mention the transcript has but its text does not - a turn sent before
 * mentions stayed in the message - as a chip beside it.
 */
export function MentionChip({ item }: { item: Mentionable }) {
  return (
    <span
      className="bg-foreground/[0.06] text-foreground inline-flex h-7 max-w-56 items-center gap-1.5 rounded-full px-2 text-xs font-medium"
      title={item.detail ?? item.name}
    >
      <MentionMark item={item} />
      <span className="truncate">{item.name}</span>
    </span>
  );
}

/** A sent address as a small card: the site's mark, its host and what is after it. */
function LinkCard({ url }: { url: string }) {
  const { host, path } = readableLink(url);
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={url}
      className="decoration-brand hover:text-brand-hover inline-flex max-w-72 items-center gap-1 align-bottom font-medium underline decoration-2 underline-offset-[3px] transition-colors"
    >
      <LinkFavicon url={url} className="h-3.5 w-3.5" />
      <span className="truncate">
        {host}
        {path && <span className="text-muted-foreground font-normal">{path}</span>}
      </span>
    </a>
  );
}

/**
 * A sent message's text, each mention in it shown as what it names - its mark
 * and name - and each address as its site's mark and a readable link.
 */
export function RichText({ text, mentions }: { text: string; mentions: readonly Mentionable[] }) {
  return (
    <>
      {richSegments(text, mentions).map((segment, index) =>
        segment.item ? (
          <span
            key={index}
            title={segment.item.detail ?? segment.item.name}
            className="bg-foreground/[0.08] text-foreground inline-flex items-center gap-1 rounded-md px-1.5 align-bottom font-medium"
          >
            <MentionMark item={segment.item} className="h-3.5 w-3.5" />
            {segment.item.name}
          </span>
        ) : segment.url ? (
          <LinkCard key={index} url={segment.url} />
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}
