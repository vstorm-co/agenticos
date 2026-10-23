"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { reasonText } from "@/components/evals/suites/suite-format";
import { Button } from "@/components/ui";
import { isLive, useEvalComparison, useEvalRun } from "@/hooks/use-eval-runs";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { EvalComparison, EvalRun } from "@/types/eval-runs";
import { Perm } from "@/types/permissions";

/** How many of a batch's latest checks are read and stated. */
const LATEST_CHECKS = 3;
/** How many broken questions a result quotes before it counts the rest. */
const QUOTED_CASES = 3;

type Translate = ReturnType<typeof useTranslations>;

/**
 * What a finished check found, in words: the cases it broke - every rerun
 * agreeing - quoted, how many it fixed, or that nothing held.
 */
export function checkFindings(comparison: EvalComparison, t: Translate, locale: string): string {
  if (comparison.verdict === "invalid") return t("invalid");
  const broken = comparison.cases.filter((item) => item.flip === "regression" && item.confirmed);
  const fixed = comparison.fixed_confirmed;
  if (broken.length === 0) return fixed > 0 ? t("fixes", { count: fixed }) : t("noChange");
  const cases = new Intl.ListFormat(locale, { type: "conjunction" }).format(
    broken.slice(0, QUOTED_CASES).map((item) => t("quote", { text: item.input })),
  );
  return t("breaks", { cases, more: Math.max(broken.length - QUOTED_CASES, 0), fixed });
}

/** What the check says as a whole: the suite's verdict when it ran on one, else the dataset. */
export function checkSentence(
  run: EvalRun,
  comparison: EvalComparison,
  t: Translate,
  locale: string,
): string {
  const findings = checkFindings(comparison, t, locale);
  const suite = run.suite_check;
  return suite?.status
    ? t("suite", { name: suite.name, status: suite.status, findings })
    : t("dataset", { name: run.dataset_name, findings });
}

function tone(run: EvalRun, comparison: EvalComparison): string {
  const status = run.suite_check?.status;
  if (status === "failed" || (!status && comparison.regressions_confirmed > 0)) {
    return "border-destructive/40 text-destructive";
  }
  if (status === "passed" || (!status && comparison.verdict === "better")) {
    return "border-success/40 text-success";
  }
  return "text-muted-foreground";
}

/**
 * One check of the authoring assistant's suggestions, stated in a sentence a
 * person can act on - "audit-smoke would fail: breaks 'Do you ship to Canada?'"
 * - and linking to its run. While it runs it says so; a check that ended
 * without completing says how.
 */
export function CheckResult({ agentId, runId }: { agentId: string; runId: string }) {
  const t = useTranslations("authoring.checkResult");
  const tSuites = useTranslations("evals.suites");
  const tc = useTranslations("common");
  const locale = useLocale();
  const { run, error } = useEvalRun(runId);
  const completed = run?.status === "completed";
  const compared = useEvalComparison(runId, { enabled: completed });
  const comparison = compared.comparison;
  const href = `${ROUTES.AGENTS}/${agentId}/evals/${runId}`;
  if (error) return <p className="text-muted-foreground text-sm">{t("unread")}</p>;
  if (!run) return null;
  if (!completed) {
    return (
      <Link
        href={href}
        className="text-muted-foreground block text-sm underline-offset-4 hover:underline"
      >
        {isLive(run.status)
          ? t("running", { name: run.dataset_name })
          : t("ended", { name: run.dataset_name, status: run.status })}
      </Link>
    );
  }
  if (compared.error) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-2 text-sm">
        <Link href={href} className="text-muted-foreground underline-offset-4 hover:underline">
          {t("unreadFindings", { name: run.dataset_name })}
        </Link>
        <Button size="sm" variant="outline" onClick={() => void compared.refetch()}>
          {tc("retry")}
        </Button>
      </div>
    );
  }
  if (!comparison) return null;
  return (
    <div className="space-y-1">
      <Link
        href={href}
        className={cn(
          "block rounded-md border px-3 py-2 text-sm underline-offset-4 hover:underline",
          tone(run, comparison),
        )}
      >
        {checkSentence(run, comparison, t, locale)}
      </Link>
      {run.suite_check && run.suite_check.reasons.length > 0 && (
        <ul className="text-muted-foreground list-disc pl-5 text-xs">
          {run.suite_check.reasons.map((reason) => (
            <li key={reason.code}>{reasonText(reason, tSuites, locale)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * A batch's latest checks, each stated. A check is an eval run, read only by a
 * reader of runs.
 */
export function CheckResults({ agentId, runIds }: { agentId: string; runIds: string[] }) {
  const { can } = usePermissions();
  if (!can(Perm.runsView)) return null;
  return (
    <div className="space-y-2">
      {runIds.slice(-LATEST_CHECKS).map((runId) => (
        <CheckResult key={runId} agentId={agentId} runId={runId} />
      ))}
    </div>
  );
}
