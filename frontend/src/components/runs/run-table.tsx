"use client";

import { useLocale, useTranslations } from "next-intl";
import { ThumbsDown } from "lucide-react";

import { RunStatusBadge } from "@/components/agents/status-badge";
import { Badge, DataTable, type Column } from "@/components/ui";
import { formatDate, formatRunDuration } from "@/lib/utils";
import type { AgentRun } from "@/types/runs";

/** The orders `GET /runs` offers, matching `RunOrder` on the backend. */
export type RunSortKey = "started_at" | "duration" | "cost";
export interface RunSort {
  by: RunSortKey;
  dir: "asc" | "desc";
}

/**
 * Run history as rows, wherever they came from.
 *
 * One table for the top level and for one run's delegations, because a row is a
 * row - what differs is which rows were asked for, and that is the caller's
 * sentence to write. The one thing the table itself must never do is let the two
 * kinds look identical: a delegated row's cost is *already inside* its parent's,
 * so a page that mixes them silently has a cost column nobody can add up. That
 * is the bug this badge exists for, next to a month-to-date figure that counts
 * each parent once.
 *
 * `sort`/`onSort` turn the Started, Took and Cost headers into sort controls.
 * Both are optional and travel together: a delegations table and a focused run
 * render the same rows with nothing to sort - the order came from the one query
 * that asked for them - so they pass neither and get plain headers. When they
 * are given, the sort is the server's over the whole narrowed set, never this
 * page of rows: the slowest run of a month is not in whichever twenty-five a
 * feed returned.
 */
export function RunTable({
  runs,
  sort,
  onSort,
}: {
  runs: AgentRun[];
  sort?: RunSort;
  onSort?: (sort: RunSort) => void;
}) {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const sortable = sort !== undefined && onSort !== undefined;

  const columns: Column<AgentRun>[] = [
    {
      key: "status",
      header: t("status"),
      cell: (run) => (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <RunStatusBadge status={run.status} />
            {/* The reason this list is worth reading top to bottom: an
                answer somebody said was wrong. A marker, not a count -
                the row links to the detail where the comment is read. */}
            {run.down_rated && (
              <ThumbsDown
                role="img"
                aria-label={t("ratedDown")}
                className="text-destructive h-3.5 w-3.5 shrink-0"
              />
            )}
          </div>
          {run.parent_run_id !== null && (
            <Badge variant="outline" className="block w-fit" title={t("delegatedCostIsAlreadyIn")}>
              {/* The task id when there is one, because it is what makes
                  this row and a delegation panel in a transcript visibly
                  the same delegation rather than two things about the same
                  agent. It is withheld for an orphan, whose parent - and
                  whose transcript - has been deleted. */}
              {run.subagent_task_id === null
                ? t("delegated")
                : t("delegatedTask", { taskId: run.subagent_task_id })}
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: "surface",
      header: t("surface"),
      cell: (run) => <span className="text-muted-foreground">{run.surface}</span>,
    },
    {
      key: "model",
      header: t("model"),
      cell: (run) => <span className="font-mono text-xs">{run.model_label ?? "-"}</span>,
    },
    {
      key: "tokens",
      header: t("tokens"),
      align: "right",
      cell: (run) => (
        <span className="font-mono text-xs">{run.input_tokens + run.output_tokens}</span>
      ),
    },
    {
      key: "cost",
      header: t("cost"),
      align: "right",
      sortable,
      cell: (run) => (
        <span className="font-mono text-xs">
          ${Number(run.cost_usd).toFixed(4)}
          {run.cost_is_partial && (
            <span className="text-muted-foreground" title={t("modelRunHadNo")}>
              {" +"}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "duration",
      header: t("took"),
      align: "right",
      sortable,
      // A still-running or parked run reads "-", the same absence the
      // duration sort places last in both directions - it has no
      // duration yet, which is a different fact from having been fast.
      cell: (run) => (
        <span className="text-muted-foreground font-mono text-xs">
          {formatRunDuration(run.started_at, run.ended_at)}
        </span>
      ),
    },
    {
      key: "started_at",
      header: t("started"),
      sortable,
      cell: (run) => (
        <span className="text-muted-foreground text-xs">
          {run.started_at === null ? "-" : formatDate(run.started_at, locale)}
        </span>
      ),
    },
  ];

  return (
    <DataTable<AgentRun>
      columns={columns}
      rows={runs}
      getRowKey={(run) => run.id}
      sort={sort}
      // The keys the two sortable columns carry are exactly `RunSortKey`, so the
      // widening to `string` on the way through the primitive is undone here.
      onSort={onSort ? (next) => onSort({ by: next.by as RunSortKey, dir: next.dir }) : undefined}
      className="rounded-none border-0 bg-transparent [&_table]:min-w-[46rem]"
    />
  );
}
