"use client";

import Link from "next/link";
import { useState } from "react";
import { Activity, Building2, Copy, Lock, Pencil, Users, Workflow } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { AgentStatusBadge } from "@/components/agents/status-badge";
import { Badge } from "@/components/ui";
import { Beam } from "@/components/ui/beam";
import { ROUTES } from "@/lib/constants";
import { cn, formatDate } from "@/lib/utils";
import type { WorkflowRead } from "@/lib/workflows/types";
import type { AgentStatus } from "@/types/agents";

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
  busy,
  onDuplicate,
}: {
  workflow: WorkflowRead;
  canCreate: boolean;
  busy?: boolean;
  onDuplicate: () => void;
}) {
  const t = useTranslations("pages.workflows");
  const tc = useTranslations("common");
  const locale = useLocale();
  const [hovered, setHovered] = useState(false);
  const status = workflow.status as AgentStatus;
  const visibility = (
    workflow.visibility in VISIBILITY_ICON ? workflow.visibility : "private"
  ) as keyof typeof VISIBILITY_ICON;
  const VisibilityIcon = VISIBILITY_ICON[visibility];

  return (
    <Beam
      size="md"
      borderRadius={12}
      active={hovered}
      onHoverChange={setHovered}
      className="rounded-xl"
    >
      <div
        className={cn(
          "border-border bg-card relative rounded-xl border p-4 transition-colors",
          "hover:border-foreground/25",
          status === "archived" && "opacity-70",
          busy && "pointer-events-none opacity-50",
        )}
      >
        <Link
          href={ROUTES.WORKFLOW_DETAIL(workflow.id)}
          className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
          aria-label={tc("openNamed", { name: workflow.name })}
        />
        <div className="pointer-events-none relative flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-300">
            <Workflow aria-hidden="true" className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-foreground truncate font-medium">{workflow.name}</p>
                <p className="text-muted-foreground truncate font-mono text-xs">{workflow.slug}</p>
              </div>
              <AgentStatusBadge status={status} />
            </div>
            <p className="text-muted-foreground mt-2 line-clamp-2 min-h-[2.5rem] text-sm">
              {workflow.description || t("noDescription")}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className="text-muted-foreground gap-1 font-normal">
                <VisibilityIcon className="h-3 w-3" aria-hidden />
                {t(`visibility.${visibility}`)}
              </Badge>
              <Badge variant="outline" className="text-muted-foreground font-normal">
                {workflow.current_version_id ? t("hasLiveVersion") : t("neverPublished")}
              </Badge>
            </div>
          </div>
        </div>

        <div className="relative mt-3 flex items-center justify-between gap-2 border-t pt-3">
          <span className="text-muted-foreground pointer-events-none text-xs">
            {workflow.updated_at
              ? t("editedWhen", { when: formatDate(workflow.updated_at, locale) })
              : t("draftRevision", { revision: workflow.draft_revision })}
          </span>
          <div className="flex items-center gap-1">
            <CardAction
              href={ROUTES.WORKFLOW_RUNS(workflow.id)}
              label={t("runsFor", { name: workflow.name })}
              icon={Activity}
            />
            <CardAction
              href={ROUTES.WORKFLOW_DETAIL(workflow.id)}
              label={tc("editNamed", { name: workflow.name })}
              icon={Pencil}
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
          </div>
        </div>
      </div>
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
  icon: typeof Pencil;
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
