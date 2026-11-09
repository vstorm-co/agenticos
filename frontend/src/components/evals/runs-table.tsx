"use client";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { DataTable, type Column } from "@/components/ui/data-table";
import { modelShortName } from "@/lib/model-profiles";
import { formatDateTime } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import type { EvalRun } from "@/types/eval-runs";
import { EvalStatusBadge } from "./eval-status-badge";
import { VerdictChip } from "./run-row";
import { percent, usd } from "./format";
import { sideName } from "./names";

export function RunsTable({
  runs,
  agentName,
}: {
  runs: EvalRun[];
  agentName?: (id: string) => string;
}) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const columns: Column<EvalRun>[] = [
    {
      key: "run",
      header: t("table.run"),
      className: "w-[60%] min-w-0 sm:w-auto",
      cell: (run) => {
        const candidate = run.arms.find((arm) => arm.role === "candidate");
        const baseline = run.outcome?.baseline ?? run.arms.find((arm) => arm.role === "baseline");
        const version = candidate ? sideName(candidate, t) : t(`status.${run.status}`);
        const title = baseline
          ? t("row.against", { candidate: version, baseline: sideName(baseline, t) })
          : version;
        return (
          <Link
            className="block min-w-0 space-y-1 hover:underline"
            href={`${ROUTES.AGENTS}/${run.agent_id}/evals/${run.id}`}
          >
            <span className="block font-medium break-words">{title}</span>
            <span className="text-muted-foreground block text-xs">
              {agentName?.(run.agent_id) ?? run.dataset_name} ·{" "}
              {formatDateTime(run.created_at, locale)}
            </span>
            <span className="flex flex-wrap gap-1 md:hidden [&_div]:max-w-full [&_div]:whitespace-normal">
              <span className="sm:hidden">
                <EvalStatusBadge status={run.status} />
              </span>
              <VerdictChip run={run} />
            </span>
          </Link>
        );
      },
    },
    {
      key: "status",
      header: t("table.status"),
      cell: (run) => <EvalStatusBadge status={run.status} />,
      hideBelow: "sm",
    },
    {
      key: "result",
      header: t("table.result"),
      cell: (run) => <VerdictChip run={run} />,
      hideBelow: "md",
    },
    {
      key: "model",
      header: t("table.model"),
      hideBelow: "lg",
      cell: (run) => (
        <div className="text-muted-foreground space-y-2 text-sm">
          {run.arms
            .filter((arm) => arm.role === "candidate")
            .map((arm) => (
              <div
                key={arm.id}
                title={arm.model_label}
                className={
                  arm.summary.incomplete + arm.summary.ungraded > 0
                    ? "flex min-h-14 items-center"
                    : "flex min-h-10 items-center"
                }
              >
                {modelShortName(arm.model_label)}
              </div>
            ))}
        </div>
      ),
    },
    {
      key: "passRate",
      header: t("table.passRate"),
      align: "right",
      cell: (run) => {
        const candidates = run.arms.filter((arm) => arm.role === "candidate");
        return (
          <div className="space-y-2 text-right tabular-nums">
            {candidates.length === 0
              ? "—"
              : candidates.map((candidate) => (
                  <div
                    key={candidate.id}
                    className={
                      candidate.summary.incomplete + candidate.summary.ungraded > 0
                        ? "min-h-14"
                        : "min-h-10"
                    }
                  >
                    <div className="text-sm font-semibold">
                      {candidate.failed_alike ? "—" : percent(candidate.summary.pass_rate, locale)}
                    </div>
                    {candidate.failed_alike ? (
                      <div className="text-muted-foreground text-xs">
                        {t("comparison.verdict.failedAlike")}
                      </div>
                    ) : (
                      <div className="text-muted-foreground text-xs">
                        {t("table.passedCount", {
                          passed: candidate.summary.passed,
                          total: candidate.summary.cases,
                        })}
                      </div>
                    )}
                    {candidate.summary.incomplete + candidate.summary.ungraded > 0 && (
                      <div className="text-muted-foreground text-xs">
                        {t("table.undecidedCount", {
                          count: candidate.summary.incomplete + candidate.summary.ungraded,
                        })}
                      </div>
                    )}
                    <div
                      className="text-muted-foreground max-w-full truncate text-xs lg:hidden"
                      title={candidate.model_label}
                    >
                      {modelShortName(candidate.model_label)}
                    </div>
                  </div>
                ))}
          </div>
        );
      },
    },
    {
      key: "cost",
      header: t("table.cost"),
      align: "right",
      cell: (run) => usd(run.cost_usd, locale),
      hideBelow: "lg",
    },
  ];
  return (
    <DataTable
      className="rounded-none border-0 [&_table]:table-fixed sm:[&_table]:table-auto"
      columns={columns}
      rows={runs}
      getRowKey={(run) => run.id}
    />
  );
}
