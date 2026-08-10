"use client";

import { useTranslations } from "next-intl";
import { ThumbsDown } from "lucide-react";

import { RunStatusBadge } from "@/components/agents/status-badge";
import { Badge, SortButton } from "@/components/ui";
import { formatDate, formatRunDuration } from "@/lib/utils";
import type { AgentRun } from "@/types/runs";

/** The two orders `GET /runs` offers, matching `RunOrder` on the backend. */
export type RunSortKey = "started_at" | "duration";
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
 * `sort`/`onSort` turn the Started and Took headers into sort controls. Both are
 * optional and travel together: a delegations table and a focused run render the
 * same rows with nothing to sort - the order came from the one query that asked
 * for them - so they pass neither and get plain headers. When they are given,
 * the sort is the server's over the whole narrowed set, never this page of rows:
 * the slowest run of a month is not in whichever twenty-five a feed returned.
 */
export function RunTable({
  runs,
  sort,
  onSort,
}: {
  runs: AgentRun[];
  sort?: RunSort;
  onSort?: (key: RunSortKey) => void;
}) {
  const t = useTranslations("pages.runs");
  const sortable = sort !== undefined && onSort !== undefined;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] text-sm">
        <thead>
          <tr className="text-muted-foreground border-b text-left">
            <th className="py-2 font-medium">{t("status")}</th>
            <th className="px-3 py-2 font-medium">{t("surface")}</th>
            <th className="px-3 py-2 font-medium">{t("model")}</th>
            <th className="px-3 py-2 text-right font-medium">{t("tokens")}</th>
            <th className="px-3 py-2 text-right font-medium">{t("cost")}</th>
            <th className="px-3 py-2 text-right font-medium">
              {sortable ? (
                <SortButton
                  active={sort.by === "duration"}
                  direction={sort.dir}
                  onClick={() => onSort("duration")}
                >
                  {t("took")}
                </SortButton>
              ) : (
                t("took")
              )}
            </th>
            <th className="px-3 py-2 font-medium">
              {sortable ? (
                <SortButton
                  active={sort.by === "started_at"}
                  direction={sort.dir}
                  onClick={() => onSort("started_at")}
                >
                  {t("started")}
                </SortButton>
              ) : (
                t("started")
              )}
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-b last:border-0">
              <td className="space-y-1 py-2">
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
                  <Badge
                    variant="outline"
                    className="block w-fit"
                    title={t("delegatedCostIsAlreadyIn")}
                  >
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
              </td>
              <td className="text-muted-foreground px-3 py-2">{run.surface}</td>
              <td className="px-3 py-2 font-mono text-xs">{run.model_label ?? "-"}</td>
              <td className="px-3 py-2 text-right font-mono text-xs">
                {run.input_tokens + run.output_tokens}
              </td>
              <td className="px-3 py-2 text-right font-mono text-xs">
                ${Number(run.cost_usd).toFixed(4)}
                {run.cost_is_partial && (
                  <span className="text-muted-foreground" title={t("modelRunHadNo")}>
                    {" +"}
                  </span>
                )}
              </td>
              {/* A still-running or parked run reads "-", the same absence the
                  duration sort places last in both directions - it has no
                  duration yet, which is a different fact from having been fast. */}
              <td className="text-muted-foreground px-3 py-2 text-right font-mono text-xs">
                {formatRunDuration(run.started_at, run.ended_at)}
              </td>
              <td className="text-muted-foreground px-3 py-2 text-xs">
                {run.started_at === null ? "-" : formatDate(run.started_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
