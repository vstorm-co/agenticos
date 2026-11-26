"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import {
  ArchiveRestore,
  CircleAlert,
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
import { SystemAgentBadge } from "@/components/agents/system-agent-badge";
import {
  Badge,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
  ResourceCard,
  ResourceCardHeader,
  ResourceCardDescription,
  ResourceCardFooter,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuItemText,
  DESCRIBED_ITEM,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn, formatDate } from "@/lib/utils";
import { isSystemAgent } from "@/lib/system-agents";
import type { Agent } from "@/types/agents";
import { useLocale, useTranslations } from "next-intl";

import { groupsLabel } from "@/components/sharing/audience-chip";
import { attentionParts } from "@/lib/attention";
import type { AgentAttention } from "@/types/stats";

/** Chip labels for the surfaces an agent answers on. Unknown values pass through. */
/**
 * Who can reach this agent, as one chip.
 *
 * Visibility answers for the broad settings; the grant count only matters for a
 * private agent, where "Private" and "Shared with 3" are different facts.
 */
export function accessSummary(
  agent: Agent,
  t: (key: string, values?: Record<string, number>) => string,
  tAudience: (key: string, values: Record<string, string | number>) => string,
): { icon: LucideIcon; label: string } {
  if (agent.visibility === "org") return { icon: Building2, label: t("visibilityOrg") };
  if (agent.visibility === "team") return { icon: Users, label: t("visibilityTeam") };
  // Its departments by name, which is what a person deciding whether to use it
  // wants to know (#2072).
  if (agent.shared_groups?.length) {
    return { icon: Users, label: groupsLabel(agent.shared_groups, tAudience) };
  }
  const count = agent.shared_user_count ?? 0;
  if (count > 0) return { icon: Users, label: t("sharedWithCount", { count }) };
  return { icon: Lock, label: t("visibilityPrivate") };
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
  footer,
  attention,
}: {
  agent: Agent;
  canEdit: boolean;
  /** The card's menu - duplicate, archive, delete. Absent for an agent the platform owns. */
  actions?: AgentCardActions;
  busy?: boolean;
  /** A line under the labels, such as the datasets a judge grades. */
  footer?: ReactNode;
  /** What makes the agent need a look lately, for a reader who may see runs. */
  attention?: AgentAttention;
}) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const locale = useLocale();
  const archived = agent.status === "archived";

  return (
    <div className="h-full">
      <ResourceCard className={cn(busy && "pointer-events-none opacity-50")}>
        <Link
          href={ROUTES.AGENT_DETAIL(agent.id)}
          className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
          aria-label={tc("openNamed", { name: agent.name })}
        />

        <ResourceCardHeader className="pointer-events-none">
          <AgentAvatar
            agentId={agent.id}
            slug={agent.slug}
            hasAvatar={agent.has_avatar}
            colorSlot={agent.avatar_color}
            size="lg"
          />
          <div className="min-w-0 flex-1 space-y-1.5">
            <h3
              className={cn(
                "text-foreground line-clamp-2 font-semibold break-words",
                archived && "text-muted-foreground",
              )}
            >
              {agent.name}
            </h3>
            <AccessChip agent={agent} />
          </div>
        </ResourceCardHeader>
        <ResourceCardDescription className="pointer-events-none">
          {agent.description || t("noDescription")}
        </ResourceCardDescription>
        <ResourceCardFooter className="pointer-events-none min-h-12">
          <AgentStatusBadge status={agent.status} compact />
          {attention && <AttentionBadge attention={attention} />}
          {isSystemAgent(agent.kind) &&
            (agent.system_key ? (
              <Badge
                variant="secondary"
                className="font-normal"
                title={t(`defaultBadge.${agent.kind}Hint`)}
              >
                {t(`defaultBadge.${agent.kind}`)}
              </Badge>
            ) : (
              <SystemAgentBadge kind={agent.kind} />
            ))}
          {footer !== undefined && <div className="w-full text-xs">{footer}</div>}
        </ResourceCardFooter>

        <div className="relative flex items-start justify-between gap-2 pt-3">
          <span
            className="text-muted-foreground pointer-events-none py-2 text-xs"
            title={`@${agent.slug}`}
          >
            {agent.updated_at
              ? t("editedWhen", { when: formatDate(agent.updated_at, locale) })
              : t("neverEdited")}
          </span>

          {canEdit && (
            <div className="flex items-center gap-1">
              <IconAction
                icon={Pencil}
                label={tc("editNamed", { name: agent.name })}
                href={ROUTES.AGENT_DETAIL(agent.id)}
                // The onboarding coach's return leg points here to reopen the very
                // agent a guided flow just built — resolved by this id, so a gallery
                // of many still returns to the right one.
                agentId={agent.id}
              />
              {actions && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      aria-label={t("moreActionsFor", { name: agent.name })}
                      className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 inline-flex h-8 w-8 touch-manipulation items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-64">
                    <DropdownMenuItem className={DESCRIBED_ITEM} onSelect={actions.onDuplicate}>
                      <Copy className="h-4 w-4" />
                      <DropdownMenuItemText
                        label={t("duplicate")}
                        description={t("menuDuplicateHint")}
                      />
                    </DropdownMenuItem>
                    {archived ? (
                      <DropdownMenuItem className={DESCRIBED_ITEM} onSelect={actions.onRestore}>
                        <ArchiveRestore className="h-4 w-4" />
                        <DropdownMenuItemText
                          label={t("restore")}
                          description={t("menuRestoreHint")}
                        />
                      </DropdownMenuItem>
                    ) : (
                      <DropdownMenuItem className={DESCRIBED_ITEM} onSelect={actions.onArchive}>
                        <Archive className="h-4 w-4" />
                        <DropdownMenuItemText
                          label={t("archive")}
                          description={t("menuArchiveHint")}
                        />
                      </DropdownMenuItem>
                    )}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className={cn(
                        DESCRIBED_ITEM,
                        "text-destructive-ink focus:text-destructive-ink",
                      )}
                      onSelect={actions.onDelete}
                    >
                      <Trash2 className="h-4 w-4" />
                      <DropdownMenuItemText
                        label={t("deletePermanently")}
                        description={t("menuDeleteHint")}
                      />
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          )}
        </div>
      </ResourceCard>
    </div>
  );
}

function AccessChip({ agent }: { agent: Agent }) {
  const t = useTranslations("agents");
  const tAudience = useTranslations("audience");
  const { icon: Icon, label } = accessSummary(agent, t, tAudience);
  return (
    <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
      <Icon className="size-3 shrink-0" aria-hidden />
      <span className="truncate" title={label}>
        {label}
      </span>
    </span>
  );
}

function IconAction({
  icon: Icon,
  label,
  href,
  agentId,
}: {
  icon: LucideIcon;
  label: string;
  href: string;
  agentId: string;
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      title={label}
      data-tour="agent-card-edit"
      data-agent-id={agentId}
      className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 inline-flex h-8 w-8 touch-manipulation items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
    >
      <Icon className="h-4 w-4" />
    </Link>
  );
}

/** A small, keyboard- and touch-readable signal with the concrete reasons. */
function AttentionBadge({ attention }: { attention: AgentAttention }) {
  const tAttention = useTranslations("attention");
  const reasons = attentionParts(attention, tAttention).join(" · ");
  const label = `${tAttention("badge")}: ${reasons}`;
  const content = (
    <>
      <p className="font-medium">{tAttention("badge")}</p>
      <p>{reasons}</p>
    </>
  );
  return (
    <TooltipProvider delayDuration={150}>
      <Popover>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label={label}
                title={reasons}
                className="text-warning-ink focus-visible:outline-ring hover:bg-warning/10 pointer-events-auto relative inline-flex size-7 shrink-0 items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <CircleAlert className="size-4" aria-hidden />
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs space-y-1">{content}</TooltipContent>
        </Tooltip>
        <PopoverContent
          className="max-w-[calc(100vw-2rem)] space-y-1 text-sm"
          onOpenAutoFocus={(event) => event.preventDefault()}
        >
          {content}
        </PopoverContent>
      </Popover>
    </TooltipProvider>
  );
}
