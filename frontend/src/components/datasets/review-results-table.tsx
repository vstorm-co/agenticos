"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Badge, DataTable, type Column } from "@/components/ui";
import { formatDateTime } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import { modelShortName } from "@/lib/model-profiles";
import type { CaseScore } from "@/types/scoring";
import { ScoreOrigin } from "./score-origin";

/** Every scored answer shares one table; opening a question keeps its review in a side panel. */
export function ReviewResultsTable({
  scores,
  linksRuns,
  question,
}: {
  scores: CaseScore[];
  linksRuns: boolean;
  question: (score: CaseScore) => ReactNode;
}) {
  const t = useTranslations("datasets.scoring");
  const table = useTranslations("datasets.resultsTable");
  const locale = useLocale();
  const columns: Column<CaseScore>[] = [
    { key: "question", header: table("question"), className: "min-w-0 md:w-[38%]", cell: question },
    {
      key: "agent",
      header: table("agent"),
      hideBelow: "sm",
      cell: (score) => (
        <div className="min-w-0">
          <p className="max-w-48 truncate text-sm">{score.agent_name ?? t("agentGone")}</p>
          {score.agent_version !== null && (
            <p className="text-muted-foreground mt-1 text-xs">
              {table("version", { number: score.agent_version })}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "result",
      header: table("result"),
      className: "w-28",
      cell: (score) => (
        <Badge variant={score.outcome === false ? "destructive" : "secondary"}>
          {t(score.outcome === true ? "passed" : score.outcome === false ? "failed" : "unscored")}
        </Badge>
      ),
    },
    {
      key: "model",
      header: table("model"),
      hideBelow: "lg",
      cell: (score) => (
        <span
          className="text-muted-foreground block max-w-52 truncate text-xs"
          title={score.run_model ?? undefined}
        >
          {score.run_model ? modelShortName(score.run_model) : "—"}
        </span>
      ),
    },
    {
      key: "date",
      header: table("date"),
      hideBelow: "md",
      cell: (score) => (
        <span className="text-muted-foreground text-xs whitespace-nowrap">
          {formatDateTime(score.created_at, locale)}
        </span>
      ),
    },
    {
      key: "source",
      header: table("source"),
      hideBelow: "lg",
      cell: (score) =>
        linksRuns && score.eval_run_id !== null && score.agent_id !== null ? (
          <Link
            href={`${ROUTES.AGENTS}/${score.agent_id}/evals/${score.eval_run_id}`}
            className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-4"
          >
            {score.skill_check || score.eval_attempt ? (
              <ScoreOrigin score={score} />
            ) : (
              t("evalRunLink")
            )}
          </Link>
        ) : (
          <ScoreOrigin score={score} />
        ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      rows={scores}
      getRowKey={(score) => score.id}
      className="[&_thead]:bg-foreground/[0.025] [&_th]:text-muted-foreground [&_tbody_tr:hover]:bg-foreground/[0.035] [&_tbody_tr:has(:focus-visible)]:bg-foreground/[0.035] [&_tbody_tr:has(:focus-visible)]:outline-ring rounded-none border-0 [&_tbody_tr:has(:focus-visible)]:outline-2 [&_tbody_tr:has(:focus-visible)]:-outline-offset-2 [&_th]:text-xs [&_th]:font-medium"
    />
  );
}
