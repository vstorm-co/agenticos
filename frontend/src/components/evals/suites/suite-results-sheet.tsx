"use client";

import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";
import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Pager,
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui";
import { useEvalSuiteResults } from "@/hooks/use-eval-suites";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import { useOrgStore } from "@/stores/org-store";
import type { EvalSuite, EvalSuiteResult } from "@/types/eval-suites";
import { Perm } from "@/types/permissions";
import { percent } from "../format";
import { RESULT_TONE, resultReasons } from "./suite-format";
import { SuitePin } from "./suite-pin";

/** What one page of results holds. */
const PAGE = 20;

/**
 * Every time a suite ran, or was due to: what started it, on which version, how
 * it came out and why - one click from the eval run behind it.
 *
 * In a right-hand drawer, opaque, as a routine's runs are: it is read, not
 * glanced at over the page.
 */
export function SuiteResultsSheet({
  suite,
  open,
  onOpenChange,
}: {
  suite: EvalSuite;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="bg-background w-full sm:max-w-xl">
        <SheetHeader className="px-5">
          <SheetTitle className="text-sm">{suite.name}</SheetTitle>
          <SheetClose onClick={() => onOpenChange(false)} />
        </SheetHeader>
        {open && <SuitePin suite={suite} />}
        {open && <SuiteResults suite={suite} />}
      </SheetContent>
    </Sheet>
  );
}

function SuiteResults({ suite }: { suite: EvalSuite }) {
  const t = useTranslations("evals.suites");
  const [page, setPage] = useState(0);
  const { results, total, isLoading, error } = useEvalSuiteResults(suite.agent_id, suite.id, {
    skip: page * PAGE,
    limit: PAGE,
  });

  if (isLoading) {
    return <LoadingState variant="skeleton-table" columns={1} rows={4} className="m-5" />;
  }
  if (error !== null) return <ErrorState title={t("resultsCouldNotBeRead")} className="m-5" />;
  if (results.length === 0) {
    return <p className="text-muted-foreground p-5 text-sm">{t("noResults")}</p>;
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <ul className="min-h-0 flex-1 divide-y overflow-y-auto">
        {results.map((result) => (
          <ResultRow key={result.id} agentId={suite.agent_id} result={result} />
        ))}
      </ul>
      <div className="border-border border-t px-5 py-3">
        <Pager
          page={page}
          pageCount={Math.max(1, Math.ceil(total / PAGE))}
          matched={total}
          total={total}
          onPage={setPage}
          counted={t("resultCount", { count: total })}
        />
      </div>
    </div>
  );
}

/** One result: when, what started it, how it came out, why - and into its run. */
function ResultRow({ agentId, result }: { agentId: string; result: EvalSuiteResult }) {
  const t = useTranslations("evals.suites");
  const locale = useLocale();
  const { can } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const summary = result.summary;
  const why = resultReasons(result, t, locale);
  const assistanceOff =
    result.reason === "ai_assistance_off" && can(Perm.orgSettings) && activeOrgId !== null;

  return (
    <li className="space-y-1.5 px-5 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={RESULT_TONE[result.status]}>{t(`status.${result.status}`)}</Badge>
        <span className="text-muted-foreground text-xs">
          {t("resultMeta", {
            trigger: result.trigger,
            version: result.version_number === null ? "none" : String(result.version_number),
            date: formatDateTime(result.settled_at ?? result.created_at, locale),
          })}
        </span>
        {result.eval_run_id && (
          <Button variant="ghost" size="sm" className="ml-auto" asChild>
            <Link href={`${ROUTES.AGENTS}/${agentId}/evals/${result.eval_run_id}`}>
              {t("openRun")}
              <ArrowUpRight className="ml-1 h-3.5 w-3.5" aria-hidden />
            </Link>
          </Button>
        )}
      </div>
      {summary?.review && <ReviewReevaluationNote review={summary.review} />}
      {summary && summary.pass_rate !== null && (
        <p className="text-muted-foreground text-xs">
          {t("passRate", {
            rate: percent(summary.pass_rate, locale),
            cases: summary.cases,
            regressions: summary.regressions_confirmed,
          })}
        </p>
      )}
      {why.map((text) => (
        <p key={text} className="text-xs">
          {text}
        </p>
      ))}
      {assistanceOff && (
        <Link
          href={`${ROUTES.ORGS}/${activeOrgId}/members`}
          className="text-xs underline underline-offset-4"
        >
          {t("enableAi")}
        </Link>
      )}
      {summary && summary.failing_cases.length > 0 && (
        <ul className="text-muted-foreground list-inside list-disc text-xs">
          {summary.failing_cases.map((failing) => (
            <li key={failing.case_id} className="truncate">
              {t(`failing.${failing.kind}`, { input: failing.input })}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
