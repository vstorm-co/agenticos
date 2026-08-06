"use client";

import { useTranslations } from "next-intl";

import { RunStatusBadge } from "@/components/agents/status-badge";
import { Badge } from "@/components/ui";
import { formatDate } from "@/lib/utils";
import type { AgentRun } from "@/types/runs";

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
 */
export function RunTable({ runs }: { runs: AgentRun[] }) {
  const t = useTranslations("pages.runs");
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm">
        <thead>
          <tr className="text-muted-foreground border-b text-left">
            <th className="py-2 font-medium">{t("status")}</th>
            <th className="px-3 py-2 font-medium">{t("surface")}</th>
            <th className="px-3 py-2 font-medium">{t("model")}</th>
            <th className="px-3 py-2 text-right font-medium">{t("tokens")}</th>
            <th className="px-3 py-2 text-right font-medium">{t("cost")}</th>
            <th className="px-3 py-2 font-medium">{t("started")}</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-b last:border-0">
              <td className="space-y-1 py-2">
                <RunStatusBadge status={run.status} />
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
