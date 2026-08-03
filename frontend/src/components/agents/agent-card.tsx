"use client";

import Link from "next/link";
import {
  ArchiveRestore,
  Archive,
  Building2,
  Copy,
  Lock,
  MoreHorizontal,
  Pencil,
  Trash2,
  Users,
  type LucideIcon,
} from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { AgentStatusBadge } from "@/components/agents/status-badge";
import {
  Badge,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn, formatDate } from "@/lib/utils";
import type { Agent } from "@/types/agents";
import { useTranslations } from "next-intl";

/** Chip labels for the surfaces an agent answers on. Unknown values pass through. */
const CHANNEL_LABEL: Record<string, string> = {
  slack: "Slack",
  telegram: "Telegram",
  mattermost: "Mattermost",
};

/**
 * Who can reach this agent, as one chip.
 *
 * Visibility answers for the broad settings; the grant count only matters for a
 * private agent, where "Private" and "Shared with 3" are different facts.
 */
export function accessSummary(agent: Agent): { icon: LucideIcon; label: string } {
  if (agent.visibility === "org") return { icon: Building2, label: "Organization" };
  if (agent.visibility === "team") return { icon: Users, label: "Team" };
  const count = agent.shared_user_count ?? 0;
  if (count > 0) return { icon: Users, label: `Shared with ${count}` };
  return { icon: Lock, label: "Private" };
}

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
  const t = useTranslations("agents");
  const archived = agent.status === "archived";

  return (
    <div
      className={cn(
        t("groupBorderBorderBg"),
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
            {agent.description || t("noDescription")}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <AccessChip agent={agent} />
            {(agent.channels ?? []).map((channel) => (
              <Badge key={channel} variant="outline" className="text-muted-foreground font-normal">
                {CHANNEL_LABEL[channel] ?? channel}
              </Badge>
            ))}
          </div>
        </div>
      </div>

      <div className="relative mt-3 flex items-center justify-between gap-2 border-t pt-3">
        <span className="text-muted-foreground pointer-events-none text-xs">
          {agent.updated_at ? `edited ${formatDate(agent.updated_at)}` : t("neverEdited")}
        </span>

        {canEdit && (
          <div className="flex items-center gap-1">
            <IconAction
              icon={Pencil}
              label={`Edit ${agent.name}`}
              href={ROUTES.AGENT_DETAIL(agent.id)}
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
                  {t("duplicate")}
                </DropdownMenuItem>
                {archived ? (
                  <DropdownMenuItem onSelect={actions.onRestore}>
                    <ArchiveRestore className="h-4 w-4" />
                    {t("restore")}
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onSelect={actions.onArchive}>
                    <Archive className="h-4 w-4" />
                    {t("archive")}
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={actions.onDelete}
                >
                  <Trash2 className="h-4 w-4" />
                  {t("deletePermanently")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>
    </div>
  );
}

function AccessChip({ agent }: { agent: Agent }) {
  const { icon: Icon, label } = accessSummary(agent);
  return (
    <Badge variant="outline" className="text-muted-foreground gap-1 font-normal">
      <Icon className="h-3 w-3" aria-hidden />
      {label}
    </Badge>
  );
}

function IconAction({
  icon: Icon,
  label,
  href,
}: {
  icon: LucideIcon;
  label: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      title={label}
      className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
    >
      <Icon className="h-4 w-4" />
    </Link>
  );
}
