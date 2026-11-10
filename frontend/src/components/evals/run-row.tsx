"use client";

import Link from "next/link";
import { XCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { EvalRun } from "@/types/eval-runs";
import { EvalStatusBadge } from "./eval-status-badge";
import { percent, usd } from "./format";
import { sideName } from "./names";
import { VERDICT_TONE } from "./verdict-headline";

/**
 * The verdict as a chip: "Breaks 2", "Worse overall · 4 broke", "First result",
 * "Pending" - and "Inconclusive" while a case is undecided and nothing broke.
 */
export function VerdictChip({ run }: { run: EvalRun }) {
  const t = useTranslations("evals.chip");
  const { outcome } = run;
  if (outcome === null) {
    return run.status === "queued" || run.status === "running" ? (
      <Badge variant="outline">{t("pending")}</Badge>
    ) : null;
  }
  if (outcome.candidate_crashed > 0) {
    return (
      <Badge variant="destructive">
        <XCircle className="h-3.5 w-3.5" aria-hidden />
        {t("crashed", { count: outcome.candidate_crashed })}
      </Badge>
    );
  }
  const broke =
    outcome.verdict === "worse" ||
    outcome.verdict === "mixed" ||
    outcome.verdict === "invalid" ||
    outcome.overall === "worse";
  if (outcome.candidate_undecided > 0 && !broke) {
    return <Badge variant="warning">{t("inconclusive")}</Badge>;
  }
  if (outcome.verdict === null) return <Badge variant="outline">{t("first")}</Badge>;
  const counts = { broke: outcome.regressions_confirmed, fixed: outcome.fixed_confirmed };
  if (outcome.overall !== null) {
    return (
      <Badge variant={outcome.overall === "worse" ? "destructive" : "success"}>
        {t("overall", { ...counts, overall: outcome.overall })}
      </Badge>
    );
  }
  return <Badge variant={VERDICT_TONE[outcome.verdict]}>{t(outcome.verdict, counts)}</Badge>;
}

/**
 * One run in a list: what was tested against what, when, on which model, how
 * it came out and what it cost. `agentName` prefixes it where runs of several
 * agents share a list.
 */
export function EvalRunRow({ run, agentName }: { run: EvalRun; agentName?: string }) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const candidates = run.arms.filter((arm) => arm.role === "candidate");
  const first = candidates[0];
  const baseline = run.outcome?.baseline ?? run.arms.find((arm) => arm.role === "baseline");
  const tested = first ? sideName(first, t) : "";
  const title = baseline
    ? t("row.against", { candidate: tested, baseline: sideName(baseline, t) })
    : tested;
  return (
    <li>
      <Link
        href={`${ROUTES.AGENTS}/${run.agent_id}/evals/${run.id}`}
        className="hover:bg-accent/40 flex flex-wrap items-center justify-between gap-3 rounded-md px-2 py-3"
      >
        <span className="max-w-full min-w-0 space-y-1">
          <span className="text-foreground block truncate text-sm font-medium">
            {agentName ? t("row.agent", { agent: agentName, title }) : title}
          </span>
          <span className="text-muted-foreground block text-xs">
            {formatDateTime(run.created_at, locale)}
          </span>
        </span>
        <span className="flex w-full max-w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-2 text-xs sm:w-auto sm:shrink-0">
          <VerdictChip run={run} />
          {candidates.map((arm) => (
            <span
              key={arm.id}
              className="text-foreground max-w-full min-w-0 break-words tabular-nums"
              title={t("row.firstRate", { rate: percent(arm.summary.first_pass_rate, locale) })}
            >
              {t("row.rate", {
                model: arm.model_label,
                rate: percent(arm.summary.pass_rate, locale),
                undecided: arm.summary.incomplete + arm.summary.ungraded,
              })}
            </span>
          ))}
          <span className="text-muted-foreground tabular-nums">{usd(run.cost_usd, locale)}</span>
          {run.status !== "completed" && <EvalStatusBadge status={run.status} />}
        </span>
      </Link>
    </li>
  );
}
