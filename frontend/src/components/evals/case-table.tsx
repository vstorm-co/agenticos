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

const ALL = "all";
const PAGE = 25;
const OUTCOMES: CaseOutcomeFilter[] = ["passed", "failed", "undecided"];

function FilterSelect({
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
 * The run's cases, narrowed by outcome and tag, each with how it moved against
 * the baseline; opening one shows every arm's answers side by side.
 */
export function CaseTable({ run, flips }: { run: EvalRun; flips: CaseFlip[] }) {
  const t = useTranslations("evals.cases");
  const tErrors = useTranslations("errors");
  const [outcome, setOutcome] = useState<string>(ALL);
  const [tag, setTag] = useState<string>(ALL);
  const [skip, setSkip] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const { cases, total, isLoading, error } = useEvalCases(run.id, {
    outcome: outcome === ALL ? null : (outcome as CaseOutcomeFilter),
    tag: tag === ALL ? null : tag,
    skip,
    limit: PAGE,
    live: run.status === "queued" || run.status === "running",
  });
  const tags = [...new Set(run.arms.flatMap((arm) => Object.keys(arm.by_tag)))].sort();
  const flipOf = new Map(flips.map((flip) => [flip.case_id, flip]));

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <CardTitle>{t("title", { count: total })}</CardTitle>
        <div className="flex flex-wrap gap-2">
          <FilterSelect
            label={t("outcomeFilter")}
            value={outcome}
            onChange={(value) => {
              setOutcome(value);
              setSkip(0);
            }}
            options={[ALL, ...OUTCOMES].map((value) => ({ value, label: t(`outcome.${value}`) }))}
          />
          {tags.length > 0 && (
            <FilterSelect
              label={t("tagFilter")}
              value={tag}
              onChange={(value) => {
                setTag(value);
                setSkip(0);
              }}
              options={[
                { value: ALL, label: t("allTags") },
                ...tags.map((value) => ({ value, label: `#${value}` })),
              ]}
            />
          )}
        </div>
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
