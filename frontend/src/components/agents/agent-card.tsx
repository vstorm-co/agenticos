"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
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
import { Beam } from "@/components/ui/beam";
import {
  Badge,
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
  const tAttention = useTranslations("attention");
  const tc = useTranslations("common");
  const locale = useLocale();
  const archived = agent.status === "archived";
  const [hovered, setHovered] = useState(false);

  return (
    // The gallery's `rise-in` animates each grid child, and the beam sets its own
    // `animation` on its wrapper while lit. Sharing one element, the beam would
    // displace the entrance and hand it back at opacity 0 when it went out - the
    // card blinking away under the cursor. The plain div keeps the two apart.
    // Full height of its grid row, so cards side by side end on one line
    // whatever their tags make of them.
    <div className="h-full">
      {/* The beam is mounted for every card and runs on the one under the cursor.
        Mounting it on hover instead would rebuild the card the mouse is over. */}
      <Beam
        size="md"
        borderRadius={12}
        active={hovered}
        onHoverChange={setHovered}
        className="h-full rounded-xl"
      >
        <div
          className={cn(
            "border-border bg-card relative flex h-full flex-col rounded-xl border p-4 transition-colors",
            "hover:border-foreground/25",
            archived && "opacity-70",
            busy && "pointer-events-none opacity-50",
          )}
        >
          <Link
            href={ROUTES.AGENT_DETAIL(agent.id)}
            className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
            aria-label={tc("openNamed", { name: agent.name })}
          />

          <div className="pointer-events-none relative mb-3 flex items-start gap-3">
            <AgentAvatar
              agentId={agent.id}
              slug={agent.slug}
              hasAvatar={agent.has_avatar}
              colorSlot={agent.avatar_color}
              size="lg"
            />
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
                {attention && (
                  <Badge
                    variant="warning"
                    className="font-normal"
                    title={attentionParts(attention, tAttention).join(" · ")}
                  >
                    {tAttention("badge")}
                  </Badge>
                )}
                {agent.system_key && agent.kind && isSystemAgent(agent.kind) && (
                  <Badge
                    variant="secondary"
                    className="font-normal"
                    title={t(`defaultBadge.${agent.kind}Hint`)}
                  >
                    {t(`defaultBadge.${agent.kind}`)}
                  </Badge>
                )}
                {(agent.channels ?? []).map((channel) => (
                  <Badge
                    key={channel}
                    variant="outline"
                    className="text-muted-foreground font-normal"
                  >
                    {CHANNEL_LABEL[channel] ?? channel}
                  </Badge>
                ))}
                {(agent.categories ?? []).map((label) => (
                  <Badge
                    key={`c:${label}`}
                    variant="outline"
                    className="text-muted-foreground font-normal"
                  >
                    {label}
                  </Badge>
                ))}
                {(agent.tags ?? []).map((label) => (
                  <Badge
                    key={`t:${label}`}
                    variant="outline"
                    className="text-muted-foreground font-normal"
                  >
                    {label}
                  </Badge>
                ))}
              </div>
              {footer !== undefined && <div className="mt-2">{footer}</div>}
            </div>
          </div>

          <div className="relative mt-auto flex items-center justify-between gap-2 border-t pt-3">
            <span className="text-muted-foreground pointer-events-none text-xs">
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
                        className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
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
                        className={cn(DESCRIBED_ITEM, "text-destructive focus:text-destructive")}
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
        </div>
      </Beam>
    </div>
  );
}

function AccessChip({ agent }: { agent: Agent }) {
  const t = useTranslations("agents");
  const tAudience = useTranslations("audience");
  const { icon: Icon, label } = accessSummary(agent, t, tAudience);
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
      className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
    >
      <Icon className="h-4 w-4" />
    </Link>
  );
}
