"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { usd } from "@/components/evals/format";
import { Button } from "@/components/ui";
import { useSkillRecheck } from "@/hooks/use-skill-improvement";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import type { SkillContinuationEstimate, SkillImprovement } from "@/types/skill-improvement";
import { CheckEstimate } from "./check-estimate";

/**
 * Measuring the result's chosen changes again on the line as it is now, once the
 * line or its agents moved since the check. Pricing spends nothing, so the price
 * and the agents it runs on are on screen first; pressing is the consent to that
 * price, and a price that moved meanwhile is shown again for a second press.
 */
export function CheckAgain({
  session,
  onStarted,
}: {
  session: SkillImprovement;
  onStarted: () => void;
}) {
  const t = useTranslations("skillImprovement.checkAgain");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { estimate, recheck } = useSkillRecheck(session.skill_id, session.id);
  const [quote, setQuote] = useState<SkillContinuationEstimate | null>(null);
  const [moved, setMoved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const price = estimate.mutateAsync;

  useEffect(() => {
    let current = true;
    price().then(
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
  }, [price, tErrors]);

  async function start(value: SkillContinuationEstimate) {
    setError(null);
    try {
      await recheck.mutateAsync(value);
      onStarted();
    } catch (failure) {
      if (!(failure instanceof ApiError && failure.status === 409)) {
        setError(getErrorMessage(failure, tErrors));
        return;
      }
      try {
        setQuote(await price());
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
      {quote && !quote.affordable && <p className="text-sm">{t("overLimit")}</p>}
      {quote && <CheckEstimate quote={quote} />}
      {error !== null && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <Button
        disabled={!quote || !quote.affordable || recheck.isPending}
        onClick={() => quote && void start(quote)}
      >
        {quote ? t("go", { cost: usd(quote.total_usd, locale) }) : t("goUnpriced")}
      </Button>
    </section>
  );
}
