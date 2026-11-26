"use client";
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Card } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import { subjectOf } from "@/lib/improvement-subject";
import { currentAttempt } from "@/lib/improvement-steps";
import type { Improvement } from "@/types/improvement";

/**
 * A search attempt's progress and the best variants it found. A score is the share of
 * required checks passed on training questions only; the verdict comes from the check
 * after Changes. At Changes, before the check, a person may bring another of the best
 * variants instead of the one the search chose.
 */
export function VariantSearch({
  session,
  choosable,
}: {
  session: Improvement;
  choosable: boolean;
}) {
  const t = useTranslations("improvement.search");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const actions = useImprovement(subjectOf(session), session.id);
  const [error, setError] = useState<string | null>(null);
  const search = currentAttempt(session)?.variant_search;
  if (!search) return null;
  const percent = (score: number | null) =>
    score === null ? "—" : new Intl.NumberFormat(locale, { style: "percent" }).format(score);
  return (
    <Card className="space-y-3 p-4 text-sm" data-tour="improvement-search">
      <h3 className="font-medium">{t("title")}</h3>
      <p>
        {t("progress", {
          tried: search.tried,
          max: search.max_variants,
          questions: search.questions,
        })}
      </p>
      <p>
        {t("spent", {
          cost: usd(search.cost_usd, locale),
          budget: usd(search.budget_usd, locale),
        })}
      </p>
      <p>{t("scores", { seed: percent(search.seed_score), best: percent(search.best_score) })}</p>
      {search.stop_reason && <p>{t(`ended.${search.stop_reason}`)}</p>}
      <p className="text-muted-foreground text-xs">{t("notVerdict")}</p>
      <p className="text-muted-foreground text-xs">{t("overshoot")}</p>
      {search.top.length > 0 && (
        <ol className="space-y-2">
          {search.top.map((variant, index) => (
            <li key={variant.id} className="space-y-1 rounded-lg border p-3">
              <p className="font-medium">
                {t("variant", { number: index + 1, score: percent(variant.train_score) })}
              </p>
              {variant.rationale && (
                <p className="text-muted-foreground text-xs">{variant.rationale}</p>
              )}
              {variant.id === search.chosen_variant_id ? (
                <p className="text-xs font-medium">{t("chosen")}</p>
              ) : (
                choosable && (
                  <Button
                    size="sm"
                    variant="outline"
                    loading={actions.chooseVariant.isPending}
                    onClick={() => {
                      setError(null);
                      actions.chooseVariant
                        .mutateAsync(variant.id)
                        .catch((failure: unknown) => setError(getErrorMessage(failure, tErrors)));
                    }}
                  >
                    {t("choose")}
                  </Button>
                )
              )}
            </li>
          ))}
        </ol>
      )}
      {error && (
        <p role="alert" className="text-destructive-ink text-sm">
          {error}
        </p>
      )}
    </Card>
  );
}
