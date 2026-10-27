"use client";

import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Input, Label } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { useImprovement } from "@/hooks/use-improvements";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { stopOf } from "@/lib/improvement-steps";
import type { ContinuationEstimate, Improvement } from "@/types/improvement";
import { useReadOnly } from "./read-only";

/**
 * The footer of a stop: what the next step does and costs, and the button that
 * starts it. Pricing spends nothing, so the price is on screen before anyone asks;
 * pressing the button is the consent to that price. When the price moved before
 * the press reached the server, the new price is shown and the person presses again.
 * Only someone who may start an improvement on the agent is offered it.
 */
export function NextStep({
  session,
  blocked,
  onStarted,
}: {
  session: Improvement;
  /** Why the step cannot start yet, said beside the button. */
  blocked?: string;
  onStarted: () => void;
}) {
  const t = useTranslations("improvement.nextUp");
  const tLimit = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const readOnly = useReadOnly();
  const actions = useImprovement(session.agent_id, session.id);
  const stop = stopOf(session);
  const [budget, setBudget] = useState(session.budget_usd);
  const [asked, setAsked] = useState(session.budget_usd);
  const [quote, setQuote] = useState<{ key: string; value: ContinuationEstimate } | null>(null);
  const [moved, setMoved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify([asked, session.status, session.stage, session.iteration]);
  const priced = quote?.key === key ? quote.value : null;
  const estimate = actions.estimateContinuation.mutateAsync;
  useEffect(() => {
    if (!stop || readOnly || session.can_restart === false) return;
    let current = true;
    estimate(asked).then(
      (value) => {
        if (current) setQuote({ key, value });
      },
      (failure: unknown) => {
        if (current) setError(getErrorMessage(failure, tErrors));
      },
    );
    return () => {
      current = false;
    };
  }, [stop, readOnly, session.can_restart, asked, key, estimate, tErrors]);
  if (!stop || readOnly || session.can_restart === false) return null;
  async function start(value: ContinuationEstimate) {
    setError(null);
    try {
      await actions.continueSession.mutateAsync(value);
      setMoved(false);
      onStarted();
    } catch (failure) {
      if (!(failure instanceof ApiError && failure.status === 409)) {
        setError(getErrorMessage(failure, tErrors));
        return;
      }
      try {
        setQuote({ key, value: await estimate(asked) });
        setMoved(true);
      } catch (again) {
        setError(getErrorMessage(again, tErrors));
      }
    }
  }
  return (
    <section
      aria-label={t("label")}
      className="border-primary/30 bg-primary/5 space-y-3 rounded-xl border p-4"
      data-tour="improvement-next-step"
    >
      <p className="text-sm">{t(`hint.${stop}`)}</p>
      {!priced && !error && (
        <p role="status" className="text-muted-foreground text-sm">
          {t("pricing")}
        </p>
      )}
      {moved && priced && (
        <p role="alert" className="text-warning text-sm">
          {t("priceMoved", { cost: usd(priced.total_usd, locale) })}
        </p>
      )}
      {priced && !priced.affordable && (
        <div className="max-w-sm space-y-2">
          <p className="text-sm">{t("overLimit")}</p>
          <Label htmlFor="next-step-budget">{tLimit("budget")}</Label>
          <div className="flex gap-2">
            <Input
              id="next-step-budget"
              type="number"
              min="0.000001"
              step="0.01"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
            />
            <Button
              variant="outline"
              disabled={!(Number(budget) > 0) || budget === asked}
              onClick={() => setAsked(budget)}
            >
              {t("raise")}
            </Button>
          </div>
        </div>
      )}
      {blocked && <p className="text-muted-foreground text-sm">{blocked}</p>}
      <Button
        className="h-auto min-h-9 whitespace-normal"
        disabled={!priced || !priced.affordable || !!blocked || actions.continueSession.isPending}
        onClick={() => priced && void start(priced)}
      >
        {priced
          ? t(`go.${stop}`, { cost: usd(priced.total_usd, locale) })
          : t(`goUnpriced.${stop}`)}
        <ArrowRight className="h-4 w-4" aria-hidden />
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </section>
  );
}
