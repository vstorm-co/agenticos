"use client";

import { ResourceIcon } from "@/components/ui/resource-icon";

import Link from "next/link";
import {
  ResourceCard,
  ResourceCardHeader,
  ResourceCardDescription,
  ResourceCardFooter,
} from "@/components/ui/resource-card";
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
} from "lucide-react";
import { useTranslations } from "next-intl";

import {
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
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
  canCreate,
  canEdit,
  busy,
  onDuplicate,
  onArchive,
  onRestore,
  onDelete,
}: {
  workflow: WorkflowRead;
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
  const [deleting, setDeleting] = useState(false);
  const archived = workflow.status === "archived";
  const live = workflow.current_version_id !== null;
  const visibility = (
    workflow.visibility in VISIBILITY_ICON ? workflow.visibility : "private"
  ) as keyof typeof VISIBILITY_ICON;
  const VisibilityIcon = VISIBILITY_ICON[visibility];

  return (
    <div className="h-full rounded-xl">
      <ResourceCard
        className={cn(archived && "opacity-70", busy && "pointer-events-none opacity-50")}
      >
        <Link
          href={ROUTES.WORKFLOW_DETAIL(workflow.id)}
          className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
          aria-label={tc("openNamed", { name: workflow.name })}
        />
        <ResourceCardHeader className="pointer-events-none">
          <ResourceIcon kind="workflow" icon={workflow.icon} />
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="text-foreground line-clamp-2 font-semibold break-words">
              {workflow.name}
            </p>
            <span
              role="img"
              aria-label={t(`visibility.${visibility}`)}
              title={t(`visibility.${visibility}`)}
              className="text-muted-foreground flex items-center gap-1.5 text-xs"
            >
              <VisibilityIcon className="size-3 shrink-0" aria-hidden />
              <span>{t(`visibility.${visibility}`)}</span>
            </span>
          </div>
        </ResourceCardHeader>
        <ResourceCardDescription className="pointer-events-none">
          {workflow.description || t("cardNoDescription")}
        </ResourceCardDescription>
        <ResourceCardFooter className="pointer-events-none justify-between">
          <span className="text-muted-foreground pointer-events-none inline-flex shrink-0 items-center gap-1.5 text-xs">
            <span
              aria-hidden
              className={cn(
                "size-1.5 rounded-full",
                archived ? "bg-muted-foreground/50" : live ? "bg-success" : "bg-warning",
              )}
            />
            {archived ? t("statusArchived") : live ? t("statusLive") : t("statusDraft")}
          </span>
          <div className="pointer-events-auto ml-auto flex items-center gap-1">
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
        </ResourceCardFooter>
      </ResourceCard>
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
    </div>
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
