"use client";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { DataTable, type Column } from "@/components/ui/data-table";
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
      cell: (run) => {
        const candidate = run.arms.find((arm) => arm.role === "candidate");
        return (
          <Link
            className="block min-w-0 space-y-1 hover:underline"
            href={`${ROUTES.AGENTS}/${run.agent_id}/evals/${run.id}`}
          >
            <span className="block font-medium break-words">
              {agentName?.(run.agent_id) ?? run.dataset_name}
            </span>
            <span className="text-muted-foreground block text-xs">
              {candidate ? sideName(candidate, t) : t(`status.${run.status}`)} ·{" "}
              {formatDateTime(run.created_at, locale)}
            </span>
            <span className="flex flex-wrap gap-1 md:hidden">
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
      key: "passRate",
      header: t("table.passRate"),
      align: "right",
      cell: (run) => {
        const candidate = run.arms.find((arm) => arm.role === "candidate");
        return (
          <span className="tabular-nums">
            {candidate ? percent(candidate.summary.pass_rate, locale) : "—"}
          </span>
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
  return <DataTable columns={columns} rows={runs} getRowKey={(run) => run.id} />;
}
