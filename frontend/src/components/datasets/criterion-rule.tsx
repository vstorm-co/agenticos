"use client";

import { ListChecks, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { CheckSummary } from "@/components/evals/check-summary";
import { Button } from "@/components/ui";
import { suggestCheck, type CheckSuggestion } from "@/lib/check-suggestions";
import type { CaseCheck } from "@/types/datasets";
import type { RubricCriterion } from "@/types/scoring";

/** What the rule suggested for a criterion checks, said the way a person would. */
function SuggestedRule({ suggestion }: { suggestion: CheckSuggestion }) {
  const t = useTranslations("datasets.scoring.ruleSuggestion");
  switch (suggestion.kind) {
    case "length":
      return <CheckSummary check={suggestion.check} />;
    case "startsWith":
      return <>{t("startsWith", { text: suggestion.text })}</>;
    default:
      return <>{t(suggestion.kind)}</>;
  }
}

/** Where a criterion's suggested rule goes: whether the dataset has it, and adding it. */
export interface RuleChecks {
  has: (check: CaseCheck) => boolean;
  /** Absent where the rule cannot be added from here. */
  onAdd?: (check: CaseCheck) => void;
}

/**
 * Under a criterion a rule can check, the rule: a rule grades the same answer
 * the same way every time, which the judge does not. Added, it joins the checks
 * every case gets.
 */
export function CriterionRule({
  criterion,
  rules,
}: {
  criterion: RubricCriterion;
  rules: RuleChecks;
}) {
  const t = useTranslations("datasets.scoring.ruleSuggestion");
  const suggestion = suggestCheck(criterion);
  if (suggestion === null) return null;
  const rule = () => (
    <span className="font-medium">
      <SuggestedRule suggestion={suggestion} />
    </span>
  );
  if (rules.has(suggestion.check)) {
    return (
      <p role="status" className="text-muted-foreground flex items-start gap-2 text-xs">
        <ListChecks className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>{t.rich("added", { rule })}</span>
      </p>
    );
  }
  const { onAdd } = rules;
  return (
    <div className="bg-muted/50 flex flex-wrap items-center gap-2 rounded-md p-2 text-xs">
      <ListChecks className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1">{t.rich("offer", { rule })}</p>
      {onAdd && (
        <Button size="sm" variant="outline" onClick={() => onAdd(suggestion.check)}>
          <Plus className="h-4 w-4" aria-hidden />
          {t("add")}
        </Button>
      )}
    </div>
  );
}
