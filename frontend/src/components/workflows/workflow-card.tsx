"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Activity,
  Archive,
  ArchiveRestore,
  Building2,
  Copy,
  Lock,
  MoreHorizontal,
  Trash2,
  Users,
  Workflow,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { WorkflowRunStatusBadge } from "@/components/workflows/runs/run-status";
import { nodeVisual } from "@/components/workflows/node-visuals";
import {
  Badge,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { Beam } from "@/components/ui/beam";
import { ROUTES } from "@/lib/constants";
import { cn, timeAgo } from "@/lib/utils";
import type { WorkflowRead } from "@/lib/workflows/types";

const VISIBILITY_ICON = { org: Building2, team: Users, private: Lock } as const;

/**
 * One workflow in the catalog - the agents gallery's card, for a workflow.
 *
 * The whole card links to the editor and the actions sit outside that link, for
 * the reason `AgentCard` gives: a button nested in an anchor navigates when you
 * meant to press it, and is invalid to a screen reader besides.
 */
export function WorkflowCard({
  workflow,
  startsFrom,
  canCreate,
  canEdit,
  busy,
  onDuplicate,
  onArchive,
  onRestore,
  onDelete,
}: {
  workflow: WorkflowRead;
  /** What the draft's first step is called in the catalog - "Webhook" - once it is known. */
  startsFrom: string | null;
  canCreate: boolean;
  /** Whether the member's role edits workflows: the menu to archive, restore or delete. */
  canEdit: boolean;
  busy?: boolean;
  onDuplicate: () => void;
  onArchive: () => void;
  onRestore: () => void;
  /** Resolves once deleted; a refusal rejects, and the card stays. */
  onDelete: () => Promise<unknown>;
}) {
  const t = useTranslations("pages.workflows");
  const tc = useTranslations("common");
  const tt = useTranslations("time");
  const locale = useLocale();
  const [hovered, setHovered] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const archived = workflow.status === "archived";
  const live = workflow.current_version_id !== null;
  // The trigger's own icon: what starts a workflow tells it apart at a glance.
  const Icon =
    workflow.entry_node === null ? Workflow : nodeVisual(workflow.entry_node, "triggers").icon;
  const visibility = (
    workflow.visibility in VISIBILITY_ICON ? workflow.visibility : "private"
  ) as keyof typeof VISIBILITY_ICON;
  const VisibilityIcon = VISIBILITY_ICON[visibility];
  const showsTrigger = workflow.trigger_active !== null && !archived;

  return (
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
          href={ROUTES.WORKFLOW_DETAIL(workflow.id)}
          className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
          aria-label={tc("openNamed", { name: workflow.name })}
        />
        <div className="pointer-events-none relative flex flex-1 items-start gap-3">
          <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-lg">
            <Icon aria-hidden="true" className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-foreground truncate font-medium">{workflow.name}</p>
                <p className="text-muted-foreground truncate text-xs">
                  {startsFrom === null
                    ? t("cardSteps", { count: workflow.step_count })
                    : t("cardStartsFrom", { trigger: startsFrom, count: workflow.step_count })}
                </p>
              </div>
              <Badge
                variant="outline"
                className="text-muted-foreground shrink-0 gap-1.5 font-normal"
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "size-1.5 rounded-full",
                    archived ? "bg-muted-foreground/50" : live ? "bg-success" : "bg-warning",
                  )}
                />
                {archived ? t("statusArchived") : live ? t("statusLive") : t("statusDraft")}
              </Badge>
            </div>
            {workflow.description && (
              <p className="text-muted-foreground mt-2 line-clamp-2 text-sm">
                {workflow.description}
              </p>
            )}
            {(showsTrigger || workflow.tags.length > 0) && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {showsTrigger && (
                  <Badge variant="outline" className="text-muted-foreground gap-1.5 font-normal">
                    <span
                      aria-hidden="true"
                      className={cn(
                        "size-1.5 rounded-full",
                        workflow.trigger_active ? "bg-emerald-500" : "bg-muted-foreground/40",
                      )}
                    />
                    {workflow.trigger_active ? t("activeOn") : t("activeOff")}
                  </Badge>
                )}
                {workflow.tags.map((tag) => (
                  <Badge key={tag} variant="secondary" className="font-normal">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="relative mt-3 flex items-center justify-between gap-2 border-t pt-3">
          <span className="text-muted-foreground pointer-events-none flex min-w-0 items-center gap-2 text-xs">
            <span
              role="img"
              aria-label={t(`visibility.${visibility}`)}
              title={t(`visibility.${visibility}`)}
              className="pointer-events-auto shrink-0"
            >
              <VisibilityIcon className="h-3.5 w-3.5" aria-hidden />
            </span>
            {workflow.last_run !== null ? (
              <>
                <WorkflowRunStatusBadge status={workflow.last_run.status} />
                {workflow.last_run.created_at !== null && (
                  <span className="truncate">
                    {timeAgo(workflow.last_run.created_at, tt, locale)}
                  </span>
                )}
              </>
            ) : (
              <span className="truncate">
                {workflow.updated_at
                  ? t("cardNotRunEdited", { when: timeAgo(workflow.updated_at, tt, locale) })
                  : t("cardNotRun")}
              </span>
            )}
          </span>
          <div className="flex items-center gap-1">
            <CardAction
              href={ROUTES.WORKFLOW_RUNS(workflow.id)}
              label={t("runsFor", { name: workflow.name })}
              icon={Activity}
            />

            {canCreate && (
              <button
                type="button"
                aria-label={t("duplicateWorkflow", { name: workflow.name })}
                title={t("duplicateWorkflow", { name: workflow.name })}
                onClick={onDuplicate}
                className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
              >
                <Copy className="h-4 w-4" />
              </button>
            )}
            {canEdit && (
              <DropdownMenu>
                <DropdownMenuTrigger
                  aria-label={t("moreFor", { name: workflow.name })}
                  className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {archived ? (
                    <>
                      <DropdownMenuItem onSelect={onRestore}>
                        <ArchiveRestore className="h-4 w-4" /> {t("restore")}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        className="text-destructive"
                        onSelect={() => setDeleting(true)}
                      >
                        <Trash2 className="h-4 w-4" /> {t("delete")}
                      </DropdownMenuItem>
                    </>
                  ) : (
                    <DropdownMenuItem onSelect={onArchive}>
                      <Archive className="h-4 w-4" /> {t("archive")}
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t("deleteTitle", { name: workflow.name })}
        description={t("deleteDescription")}
        confirmLabel={t("delete")}
        destructive
        onConfirm={() =>
          onDelete().then(
            () => setDeleting(false),
            () => setDeleting(false),
          )
        }
      />
    </Beam>
  );
}

function CardAction({
  href,
  label,
  icon: Icon,
}: {
  href: string;
  label: string;
  icon: typeof Activity;
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
