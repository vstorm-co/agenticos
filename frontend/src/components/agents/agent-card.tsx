"use client";

import Link from "next/link";
import {
  ArchiveRestore,
  Archive,
  Copy,
  MoreHorizontal,
  Pencil,
  Trash2,
  type LucideIcon,
} from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { AgentStatusBadge } from "@/components/agents/status-badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn, formatDate } from "@/lib/utils";
import type { Agent } from "@/types/agents";

export interface AgentCardActions {
  onDuplicate: () => void;
  onArchive: () => void;
  onRestore: () => void;
  onDelete: () => void;
}

/**
 * One agent in the gallery.
 *
 * The whole card is the link to the builder, and the menu sits outside it -
 * nesting a button inside an anchor produces an element that navigates when you
 * meant to open a menu, and a nested interactive is invalid to a screen reader
 * besides.
 */
export function AgentCard({
  agent,
  canEdit,
  actions,
  busy,
}: {
  agent: Agent;
  canEdit: boolean;
  actions: AgentCardActions;
  busy?: boolean;
}) {
  const archived = agent.status === "archived";

  return (
    <div
      className={cn(
        "group border-border bg-card relative rounded-xl border p-4 transition-colors",
        "hover:border-foreground/25",
        archived && "opacity-70",
        busy && "pointer-events-none opacity-50",
      )}
    >
      <Link
        href={ROUTES.AGENT_DETAIL(agent.id)}
        className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
        aria-label={`Open ${agent.name}`}
      />

      <div className="pointer-events-none relative flex items-start gap-3">
        <AgentAvatar agentId={agent.id} name={agent.name} hasAvatar={agent.has_avatar} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-foreground truncate font-medium">{agent.name}</p>
              <p className="text-muted-foreground truncate font-mono text-xs">@{agent.slug}</p>
            </div>
            <AgentStatusBadge status={agent.status} />
          </div>
          <p className="text-muted-foreground mt-2 line-clamp-2 min-h-[2.5rem] text-sm">
            {agent.description || "No description."}
          </p>
        </div>
      </div>

      <div className="relative mt-3 flex items-center justify-between gap-2 border-t pt-3">
        <span className="text-muted-foreground pointer-events-none font-mono text-[11px]">
          {agent.updated_at ? `edited ${formatDate(agent.updated_at)}` : "never edited"}
        </span>

        {canEdit && (
          <div className="flex items-center gap-1">
            <IconAction
              icon={Pencil}
              label={`Edit ${agent.name}`}
              href={ROUTES.AGENT_DETAIL(agent.id)}
            />
            <IconAction
              icon={Copy}
              label={`Duplicate ${agent.name}`}
              onClick={actions.onDuplicate}
            />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={`More actions for ${agent.name}`}
                  className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={actions.onDuplicate}>
                  <Copy className="h-4 w-4" />
                  Duplicate
                </DropdownMenuItem>
                {archived ? (
                  <DropdownMenuItem onSelect={actions.onRestore}>
                    <ArchiveRestore className="h-4 w-4" />
                    Restore
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onSelect={actions.onArchive}>
                    <Archive className="h-4 w-4" />
                    Archive
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={actions.onDelete}
                >
                  <Trash2 className="h-4 w-4" />
                  Delete permanently
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>
    </div>
  );
}

function IconAction({
  icon: Icon,
  label,
  href,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  href?: string;
  onClick?: () => void;
}) {
  const className =
    "text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2";

  if (href) {
    return (
      <Link href={href} aria-label={label} title={label} className={className}>
        <Icon className="h-4 w-4" />
      </Link>
    );
  }
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className={className}>
      <Icon className="h-4 w-4" />
    </button>
  );
}
