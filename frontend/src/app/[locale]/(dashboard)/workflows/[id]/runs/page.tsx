"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { Play } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState } from "@/components/states";
import { Button, Column, DataTable, ListCard } from "@/components/ui";
import { StartRunDialog } from "@/components/workflows/runs/start-run-dialog";
import { WorkflowRunStatusBadge } from "@/components/workflows/runs/run-status";
import { usePermissions, useWorkflow, useWorkflowRuns } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatDateTime, formatRunDuration } from "@/lib/utils";
import type { WorkflowRunRead } from "@/lib/workflows/types";
import { Perm } from "@/types/permissions";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * A workflow's runs, newest first, and starting one by hand.
 *
 * The list polls while any run on it is still moving, so a run started here
 * walks through its statuses without a reload. A row opens the run.
 */
export default function WorkflowRunsPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("pages.workflows");
  const locale = useLocale();
  const router = useRouter();
  const { workflow } = useWorkflow(id);
  const { runs, total, isLoading, start } = useWorkflowRuns(id);
  const { can } = usePermissions();
  const [startOpen, setStartOpen] = useState(false);
  const canTest = can(Perm.workflowsEdit) && workflow?.status !== "archived";
  const canRunLive = can(Perm.workflowsRun) && workflow?.current_version_id != null;

  const columns: Column<WorkflowRunRead>[] = [
    {
      key: "status",
      header: t("runColumns.status"),
      cell: (run) => <WorkflowRunStatusBadge status={run.status} />,
    },
    {
      key: "mode",
      header: t("runColumns.mode"),
      cell: (run) => (run.mode === "test" ? t("modeTest") : t("modeReal")),
    },
    {
      key: "trigger",
      header: t("runColumns.trigger"),
      cell: (run) => t(`trigger.${run.triggered_by}`),
      hideBelow: "md",
    },
    {
      key: "started",
      header: t("runColumns.started"),
      cell: (run) => (run.started_at ? formatDateTime(run.started_at, locale) : "—"),
    },
    {
      key: "duration",
      header: t("runColumns.duration"),
      cell: (run) => formatRunDuration(run.started_at, run.ended_at),
      hideBelow: "sm",
    },
    {
      key: "cost",
      header: t("runColumns.cost"),
      align: "right",
      cell: (run) => `$${run.spent_cost.toFixed(4)}${run.cost_is_partial ? "+" : ""}`,
      hideBelow: "md",
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("runsTitle")}
        description={t("runsDescription")}
        breadcrumbs={[
          { label: t("title"), href: ROUTES.WORKFLOWS },
          { label: workflow?.name ?? t("runsTitle"), href: ROUTES.WORKFLOW_DETAIL(id) },
          { label: t("runsTitle") },
        ]}
        actions={
          canTest || canRunLive ? (
            <Button onClick={() => setStartOpen(true)}>
              <Play className="h-4 w-4" />
              {t("startRun")}
            </Button>
          ) : undefined
        }
      />
      <ListCard
        title={t("runsTitle")}
        counted={isLoading ? null : t("runsCount", { count: total })}
      >
        <DataTable
          columns={columns}
          rows={runs}
          getRowKey={(run) => run.id}
          loading={isLoading}
          onRowClick={(run) => router.push(ROUTES.WORKFLOW_RUN_DETAIL(id, run.id))}
          empty={<EmptyState title={t("runsEmpty")} description={t("runsEmptyDetail")} />}
        />
      </ListCard>
      {startOpen && (
        <StartRunDialog
          open
          onOpenChange={setStartOpen}
          canRunLive={canRunLive}
          canTest={canTest}
          busy={start.isPending}
          onStart={({ mode, input }) =>
            start.mutate(
              { workflow_id: id, mode, input },
              {
                onSuccess: (run) => {
                  setStartOpen(false);
                  router.push(ROUTES.WORKFLOW_RUN_DETAIL(id, run.id));
                },
              },
            )
          }
        />
      )}
    </div>
  );
}
