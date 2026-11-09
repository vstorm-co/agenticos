"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { limitText, limitValue, usd } from "@/components/evals/format";
import { Button, Input, Label } from "@/components/ui";
import { useSkillRecheck } from "@/hooks/use-skill-improvement";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import type { SkillContinuationEstimate, SkillImprovement } from "@/types/skill-improvement";
import { CheckEstimate } from "./check-estimate";

/**
 * Measuring the result's chosen changes again on the line as it is now, once the
 * line or its agents moved since the check. Pricing spends nothing, so the price
 * and the agents it runs on are on screen first; pressing is the consent to that
 * price, and a price that moved meanwhile is shown again for a second press. A price
 * over what the session has left takes a higher limit for this check, priced again
 * against that limit.
 */
export function CheckAgain({
  session,
  onStarted,
}: {
  session: SkillImprovement;
  onStarted: () => void;
}) {
  const t = useTranslations("skillImprovement.checkAgain");
  const tLimit = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { estimate, recheck } = useSkillRecheck(session.skill_id, session.id);
  const [quote, setQuote] = useState<SkillContinuationEstimate | null>(null);
  const [moved, setMoved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [budget, setBudget] = useState(() => limitText(session.budget_usd, locale));
  const [asked, setAsked] = useState(session.budget_usd);
  const price = estimate.mutateAsync;

  // A raised limit is priced again: what the session spent counts against it too.
  useEffect(() => {
    let current = true;
    price(asked).then(
      (value) => {
        if (current) setQuote(value);
      },
      (failure: unknown) => {
        if (current) setError(getErrorMessage(failure, tErrors));
      },
    );
    return () => {
      current = false;
    };
  }, [price, asked, tErrors]);

  async function start(value: SkillContinuationEstimate) {
    setError(null);
    try {
      await recheck.mutateAsync({ quote: value, budget: asked });
      onStarted();
    } catch (failure) {
      if (!(failure instanceof ApiError && failure.status === 409)) {
        setError(getErrorMessage(failure, tErrors));
        return;
      }
      try {
        setQuote(await price(asked));
        setMoved(true);
      } catch (again) {
        setError(getErrorMessage(again, tErrors));
      }
    }
  }

  return (
    <section className="border-warning/40 space-y-3 rounded-xl border p-4">
      <p className="text-sm">{t("why")}</p>
      {!quote && !error && (
        <p role="status" className="text-muted-foreground text-sm">
          {t("pricing")}
        </p>
      )}
      {moved && quote && (
        <p role="alert" className="text-warning text-sm">
          {t("priceMoved", { cost: usd(quote.total_usd, locale) })}
        </p>
      )}
      {quote && !quote.affordable && (
        <div className="max-w-sm space-y-2">
          <p className="text-sm">{t("overLimit")}</p>
          <Label htmlFor="check-again-budget">{tLimit("budget")}</Label>
          <div className="flex gap-2">
            <Input
              id="check-again-budget"
              inputMode="decimal"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
            />
            <Button
              variant="outline"
              disabled={
                !(Number(limitValue(budget)) > 0) || Number(limitValue(budget)) === Number(asked)
              }
              onClick={() => setAsked(limitValue(budget))}
            >
              {t("raise")}
            </Button>
          </div>
        </div>
      )}
      {quote && <CheckEstimate quote={quote} />}
      {error !== null && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <Button
        disabled={!quote?.affordable || recheck.isPending}
        onClick={() => quote && void start(quote)}
      >
        {quote ? t("go", { cost: usd(quote.total_usd, locale) }) : t("goUnpriced")}
      </Button>
    </section>
  );
}
