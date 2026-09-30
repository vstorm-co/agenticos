"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState } from "@/components/states";
import {
  Column,
  DataTable,
  ListCard,
  PaginationBar,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useRunHistory, useUrlState, useWorkflows } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatDateTime, formatRunDuration } from "@/lib/utils";
import { RUN_HISTORY_PAGE } from "@/lib/workflows/runs-api";
import type { WorkflowRunRead, WorkflowRunStatus } from "@/lib/workflows/types";

import { WorkflowRunStatusBadge, RUN_DOT } from "./run-status";

const ALL = "all";
const STATUSES = Object.keys(RUN_DOT) as WorkflowRunStatus[];
const MODES = ["test", "real"] as const;
const TRIGGERS = ["api", "websocket", "webhook", "chat", "schedule", "table_created"] as const;

/**
 * A run history: newest first, a page at a time, narrowed by state, by draft or
 * published version and by what started it - every filter applied on the server,
 * and each kept in the address so a filtered list can be linked. One workflow's
 * runs, or with no `workflowId` every workflow's the caller may see, each row
 * naming its workflow. A row opens the run.
 */
export function RunHistory({ workflowId }: { workflowId?: string }) {
  const t = useTranslations("pages.workflows");
  const locale = useLocale();
  const router = useRouter();
  const [status, setStatus] = useUrlState("status");
  const [mode, setMode] = useUrlState("mode");
  const [trigger, setTrigger] = useUrlState("trigger");
  const [pageParam, setPage] = useUrlState("page");
  const page = Math.max(0, Number(pageParam ?? "0") || 0);
  const { runs, total, isLoading } = useRunHistory({
    workflowId,
    status: (status ?? undefined) as WorkflowRunStatus | undefined,
    mode: (mode ?? undefined) as "real" | "test" | undefined,
    triggeredBy: trigger ?? undefined,
    page,
  });
  const { workflows } = useWorkflows({ enabled: workflowId === undefined });
  const names = new Map(workflows.map((workflow) => [workflow.id, workflow.name]));

  /** A filter changed: back to the first page, which is where its results start. */
  const narrow = (set: (value: string | null) => void) => (value: string) => {
    set(value === ALL ? null : value);
    setPage(null);
  };

  const columns: Column<WorkflowRunRead>[] = [
    ...(workflowId === undefined
      ? [
          {
            key: "workflow",
            header: t("runColumns.workflow"),
            cell: (run: WorkflowRunRead) => names.get(run.workflow_id) ?? "—",
          },
        ]
      : []),
    {
      key: "status",
      header: t("runColumns.status"),
      cell: (run) => (
        <span className="inline-flex items-center gap-1.5">
          <WorkflowRunStatusBadge status={run.status} />
          {run.retry_of_run_id !== null && (
            <span className="text-muted-foreground text-xs">{t("runRetryMark")}</span>
          )}
        </span>
      ),
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

  const filtered = status !== null || mode !== null || trigger !== null;
  return (
    <ListCard
      title={t("runsTitle")}
      counted={isLoading ? null : t("runsCount", { count: total })}
      data-tour={workflowId === undefined ? "workflows-runs" : undefined}
      controls={
        <div className="flex flex-wrap items-center gap-2">
          <Filter
            label={t("runFilterStatus")}
            value={status ?? ALL}
            onChange={narrow(setStatus)}
            options={STATUSES.map((value) => [value, t(`runStatus.${value}`)])}
          />
          <Filter
            label={t("runFilterMode")}
            value={mode ?? ALL}
            onChange={narrow(setMode)}
            options={MODES.map((value) => [
              value,
              value === "test" ? t("modeTest") : t("modeReal"),
            ])}
          />
          <Filter
            label={t("runFilterTrigger")}
            value={trigger ?? ALL}
            onChange={narrow(setTrigger)}
            options={TRIGGERS.map((value) => [value, t(`trigger.${value}`)])}
          />
        </div>
      }
    >
      <DataTable
        columns={columns}
        rows={runs}
        getRowKey={(run) => run.id}
        loading={isLoading}
        onRowClick={(run) => router.push(ROUTES.WORKFLOW_RUN_DETAIL(run.workflow_id, run.id))}
        empty={
          filtered ? (
            <EmptyState title={t("runsNoMatch")} description={t("runsNoMatchDetail")} />
          ) : (
            <EmptyState title={t("runsEmpty")} description={t("runsEmptyDetail")} />
          )
        }
      />
      <PaginationBar
        page={page}
        pageSize={RUN_HISTORY_PAGE}
        total={total}
        isLoading={isLoading}
        onPage={(next) => setPage(next === 0 ? null : String(next))}
      />
    </ListCard>
  );
}

function Filter({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  const t = useTranslations("pages.workflows");
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 w-auto min-w-32 text-xs" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{t("runFilterAny", { filter: label })}</SelectItem>
        {options.map(([option, text]) => (
          <SelectItem key={option} value={option}>
            {text}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
