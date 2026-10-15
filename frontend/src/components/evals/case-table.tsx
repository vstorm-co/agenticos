"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
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
import type { CaseFlip, CaseOutcomeFilter, EvalRun } from "@/types/eval-runs";
import { CaseDetail } from "./case-detail";

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

/**
 * The run's cases, narrowed by outcome and by the tag the run view is read
 * under, each with how it moved against the baseline; opening one shows every
 * arm's answers side by side.
 */
export function CaseTable({
  run,
  flips,
  tag,
}: {
  run: EvalRun;
  flips: CaseFlip[];
  tag: string | null;
}) {
  const t = useTranslations("evals.cases");
  const tErrors = useTranslations("errors");
  const [outcome, setOutcome] = useState<string>(ALL);
  const [skip, setSkip] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  // Page three of one tag's cases is not page three of another's.
  const [seenTag, setSeenTag] = useState(tag);
  if (seenTag !== tag) {
    setSeenTag(tag);
    setSkip(0);
  }
  const { cases, total, isLoading, error } = useEvalCases(run.id, {
    outcome: outcome === ALL ? null : (outcome as CaseOutcomeFilter),
    tag,
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
                    <span className="min-w-0 flex-1 truncate text-sm">{item.input}</span>
                    {flip && flip.flip !== "unchanged" && (
                      <Badge variant={flip.flip === "regression" ? "destructive" : "secondary"}>
                        {t(`flip.${flip.flip}`, { confirmed: String(flip.confirmed) })}
                      </Badge>
                    )}
                  </button>
                  {expanded && (
                    <div className="mt-3">
                      <CaseDetail attempts={item.attempts} arms={run.arms} />
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
