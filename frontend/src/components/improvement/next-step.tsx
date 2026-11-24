"use client";

import { type ReactNode, useCallback, useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Input, Label } from "@/components/ui";
import { limitText, limitValue, usd } from "@/components/evals/format";
import { useImprovement } from "@/hooks/use-improvements";
import { mayContinue, subjectOf } from "@/lib/improvement-subject";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { currentAttempt, stopOf } from "@/lib/improvement-steps";
import type { ContinuationEstimate, Improvement } from "@/types/improvement";
import { ContinueSession } from "./continue-session";
import { EvidenceOnly, evidenceOnlyDataset } from "./evidence-only";
import { useReadOnly } from "./read-only";

/**
 * The footer of a stop: what the next step does and costs, and the button that
 * starts it. Pricing spends nothing, so the price is on screen before anyone asks;
 * pressing the button is the consent to that price. When the price moved before
 * the press reached the server, the new price is shown and the person presses again;
 * so is a skill line that got a newer version meanwhile, and edits that no longer
 * apply to it leave trying again. Only someone who may start an improvement on the agent is offered it.
 */
export function NextStep({
  session,
  hint,
  detail,
  blocked,
  hold = false,
  revision = null,
  body,
  onStarted,
}: {
  session: Improvement;
  /** What to do before pressing, when the stop's own hint does not fit. */
  hint?: string;
  /** What the priced step will do, said under its price - a skill's check names its agents. */
  detail?: (quote: ContinuationEstimate) => ReactNode;
  /** Why the step cannot start yet, said beside the button. */
  blocked?: string;
  /** What blocks the step also changes what it would measure, so it is not priced yet. */
  hold?: boolean;
  /** Changes when what the step measures changed without the session moving; it is priced again. */
  revision?: string | null;
  /**
   * What the step is priced and started with beside the limit. A new value prices it
   * again, so the caller keeps it stable between renders.
   */
  body?: Record<string, unknown>;
  onStarted: () => void;
}) {
  const t = useTranslations("improvement.nextUp");
  const tLimit = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const readOnly = useReadOnly();
  const actions = useImprovement(subjectOf(session), session.id);
  const stop = stopOf(session);
  const [budget, setBudget] = useState(() => limitText(session.budget_usd, locale));
  const [asked, setAsked] = useState(session.budget_usd);
  const [quote, setQuote] = useState<{ key: string; value: ContinuationEstimate } | null>(null);
  // A skill's line can get a newer version under a stop; the step is then priced on it.
  const [moved, setMoved] = useState<"price" | "line" | null>(null);
  const [stuck, setStuck] = useState(false);
  // A refusal belongs to the price it answered, so pricing again clears it.
  const [said, setSaid] = useState<{
    key: string;
    text: string;
    dataset: string | null;
  } | null>(null);
  // Choosing or rewording a change changes what the check measures, and so its price.
  const candidate = currentAttempt(session)?.candidate_spec_hash;
  const key = JSON.stringify([
    asked,
    session.status,
    session.stage,
    session.iteration,
    candidate,
    body,
    hold,
    revision,
  ]);
  const priced = quote?.key === key ? quote.value : null;
  const error = said?.key === key ? said.text : null;
  const estimate = actions.estimateContinuation.mutateAsync;
  // Too few questions kept aside is final for this session: it keeps the questions it began with.
  const refusal = useCallback(
    (cause: unknown) => {
      const missing = cause instanceof ApiError ? cause.details?.missing_holdout : undefined;
      return typeof missing === "number"
        ? t("unmeasurable", { count: missing })
        : getErrorMessage(cause, tErrors);
    },
    [t, tErrors],
  );
  const blockedBy = session.next_step_blocked;
  const allowed = mayContinue(session);
  useEffect(() => {
    if (!stop || readOnly || !allowed || blockedBy || hold) return;
    let current = true;
    estimate({ budget: asked, body }).then(
      (value) => {
        if (current) setQuote({ key, value });
      },
      (refused: unknown) => {
        if (current)
          setSaid({ key, text: refusal(refused), dataset: evidenceOnlyDataset(refused) });
      },
    );
    return () => {
      current = false;
    };
  }, [stop, readOnly, allowed, blockedBy, hold, asked, body, key, estimate, refusal]);
  if (!stop || readOnly || !allowed) return null;
  const evidence = blockedBy || said?.key !== key ? null : said.dataset;
  const refused = blockedBy ? t("unmeasurable", { count: blockedBy.needed }) : error;
  async function start(value: ContinuationEstimate) {
    setSaid(null);
    try {
      await actions.continueSession.mutateAsync({ ...value, body });
      setMoved(null);
      setStuck(false);
      onStarted();
    } catch (cause) {
      if (!(cause instanceof ApiError && cause.status === 409)) {
        setSaid({
          key,
          text: getErrorMessage(cause, tErrors),
          dataset: evidenceOnlyDataset(cause),
        });
        return;
      }
      const line = cause.code === "LINE_MOVED";
      try {
        setQuote({ key, value: await estimate({ budget: asked, body }) });
        setMoved(line ? "line" : "price");
        setStuck(false);
      } catch (again) {
        setSaid({ key, text: refusal(again), dataset: evidenceOnlyDataset(again) });
        setStuck(line);
      }
    }
  }
  return (
    <section
      aria-label={t("label")}
      className="border-primary/30 bg-primary/5 space-y-3 rounded-xl border p-4"
      data-tour="improvement-next-step"
    >
      <p className="text-sm">{hint ?? t(`hint.${stop}`)}</p>
      {!priced && !refused && !hold && (
        <p role="status" className="text-muted-foreground text-sm">
          {t("pricing")}
        </p>
      )}
      {moved && priced && (
        <p role="alert" className="text-warning-ink text-sm">
          {t(moved === "line" ? "lineMoved" : "priceMoved", {
            cost: usd(priced.total_usd, locale),
          })}
        </p>
      )}
      {priced && !priced.affordable && (
        <div className="max-w-sm space-y-2">
          <p className="text-sm">{t("overLimit")}</p>
          <Label htmlFor="next-step-budget">{tLimit("budget")}</Label>
          <div className="flex gap-2">
            <Input
              id="next-step-budget"
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
      {priced && detail?.(priced)}
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
      {priced?.expected_usd && Number(priced.expected_usd) < Number(priced.total_usd) && (
        <p className="text-muted-foreground text-xs">
          {t("likely", { cost: usd(priced.expected_usd, locale) })}
        </p>
      )}
      {evidence ? (
        <EvidenceOnly datasetId={evidence} />
      ) : (
        refused && (
          <p role="alert" className="text-destructive-ink text-sm">
            {refused}
          </p>
        )
      )}
      {stuck && <ContinueSession session={session} onStarted={onStarted} />}
    </section>
  );
}
