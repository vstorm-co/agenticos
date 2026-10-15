"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  PaginationBar,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useEvalCases } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import type {
  CaseFlip,
  CaseOutcomeFilter,
  EvalAttempt,
  EvalRun,
  EvalRunArm,
} from "@/types/eval-runs";
import { CaseDetail } from "./case-detail";
import { sideName } from "./names";

export const ALL = "all";
const PAGE = 25;
const OUTCOMES: CaseOutcomeFilter[] = ["passed", "failed", "undecided"];

export function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} className="h-8 w-44">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

type DotState = "passed" | "failed" | "undecided" | "pending";

const DOT_CLASS: Record<DotState, string> = {
  passed: "bg-success",
  failed: "bg-destructive",
  undecided: "bg-warning",
  pending: "border-muted-foreground border bg-transparent",
};

function dotState(attempt: EvalAttempt | undefined): DotState {
  if (attempt === undefined || attempt.status === "pending" || attempt.status === "running") {
    return "pending";
  }
  if (attempt.outcome === null) return "undecided";
  return attempt.outcome ? "passed" : "failed";
}

/** Whether a person's review overturned what the scorers concluded. */
function corrected(attempt: EvalAttempt): boolean {
  const score = attempt.score;
  return score !== null && score.human_passed !== null && score.human_passed !== score.passed;
}

/** How each side's first answer to a case came out, one dot per side. */
function SideDots({ attempts, arms }: { attempts: EvalAttempt[]; arms: EvalRunArm[] }) {
  const t = useTranslations("evals");
  return (
    <span className="flex shrink-0 items-center gap-1">
      {arms.map((arm) => {
        const state = dotState(
          attempts.find((attempt) => attempt.arm_id === arm.id && attempt.attempt === 0),
        );
        const label = t("cases.dot", {
          side: t("sideModel", { name: sideName(arm, t), model: arm.model_label }),
          state,
        });
        return (
          <span
            key={arm.id}
            role="img"
            aria-label={label}
            title={label}
            className={cn("h-2.5 w-2.5 rounded-full", DOT_CLASS[state])}
          />
        );
      })}
    </span>
  );
}

/**
 * The run's cases, narrowed by outcome and by the tag the run view is read
 * under, each with how it moved against the baseline; opening one shows every
 * arm's answers side by side.
 */
export function CaseTable({
  run,
  flips,
  tag,
  caseIds,
  onShowAll,
}: {
  run: EvalRun;
  flips: CaseFlip[];
  tag: string | null;
  /** Only these cases - the ones that broke - until `onShowAll`. */
  caseIds: string[] | null;
  onShowAll: () => void;
}) {
  const t = useTranslations("evals.cases");
  const tErrors = useTranslations("errors");
  const [outcome, setOutcome] = useState<string>(ALL);
  const [skip, setSkip] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  // Page three of one tag's cases is not page three of another's. Compared as a
  // value: the ids arrive as a new array on every render.
  const scope = JSON.stringify([tag, caseIds]);
  const [seenScope, setSeenScope] = useState(scope);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setSkip(0);
  }
  const { cases, total, isLoading, error } = useEvalCases(run.id, {
    outcome: outcome === ALL ? null : (outcome as CaseOutcomeFilter),
    tag,
    caseIds,
    skip,
    limit: PAGE,
    live: run.status === "queued" || run.status === "running",
  });
  const flipOf = new Map(flips.map((flip) => [flip.case_id, flip]));

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <CardTitle>{t("title", { count: total })}</CardTitle>
        <FilterSelect
          label={t("outcomeFilter")}
          value={outcome}
          onChange={(value) => {
            setOutcome(value);
            setSkip(0);
          }}
          options={[ALL, ...OUTCOMES].map((value) => ({ value, label: t(`outcome.${value}`) }))}
        />
      </CardHeader>
      <CardContent>
        {caseIds !== null && (
          <p className="text-muted-foreground mb-2 flex flex-wrap items-center gap-2 text-sm">
            {t("brokenOnly", { count: caseIds.length })}
            <Button size="sm" variant="ghost" onClick={onShowAll}>
              {t("showAll")}
            </Button>
          </p>
        )}
        {isLoading ? (
          <LoadingState variant="skeleton-list" rows={4} />
        ) : error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : (
          <ul className="divide-border divide-y">
            {cases.map((item) => {
              const flip = flipOf.get(item.case_id);
              const expanded = open === item.case_id;
              return (
                <li key={item.case_id} className="py-2">
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => setOpen(expanded ? null : item.case_id)}
                    className="flex w-full items-center gap-2 text-left"
                  >
                    {expanded ? (
                      <ChevronDown className="h-4 w-4 shrink-0" aria-hidden />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0" aria-hidden />
                    )}
                    <SideDots attempts={item.attempts} arms={run.arms} />
                    <span className="min-w-0 flex-1 truncate text-sm">{item.input}</span>
                    {item.attempts.some(corrected) && (
                      <Badge variant="outline">{t("corrected")}</Badge>
                    )}
                    {flip && flip.flip !== "unchanged" && (
                      <Badge variant={flip.flip === "regression" ? "destructive" : "secondary"}>
                        {t(`flip.${flip.flip}`, { confirmed: String(flip.confirmed) })}
                      </Badge>
                    )}
                  </button>
                  {expanded && (
                    <div className="mt-3">
                      <CaseDetail
                        attempts={item.attempts}
                        arms={run.arms}
                        expectation={item.expectation}
                        datasetId={run.dataset_id}
                        caseId={item.case_id}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <PaginationBar
          page={skip / PAGE}
          pageSize={PAGE}
          total={total}
          onPage={(page) => setSkip(page * PAGE)}
        />
      </CardContent>
    </Card>
  );
}
