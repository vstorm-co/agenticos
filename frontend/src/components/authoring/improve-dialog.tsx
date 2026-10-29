"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { SystemAgentChoice } from "@/components/agents/system-agent-choice";
import { usd } from "@/components/evals/format";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { AuthoringEstimate, AuthoringKind, AuthoringStart } from "@/types/authoring";

/**
 * What an Improve or Verify would read and cost, asked before anything is spent.
 *
 * Starting is a separate click: the estimate writes nothing and calls no model,
 * so the person sees the runs it would read and the price first.
 */
export function ImproveDialog({
  kind,
  estimate,
  start,
  onOpenChange,
}: {
  kind: AuthoringKind;
  estimate: (body: AuthoringStart) => Promise<AuthoringEstimate>;
  start: (body: AuthoringStart) => Promise<unknown>;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("authoring.improve");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const [improverId, setImproverId] = useState<string | null>(null);
  const [quote, setQuote] = useState<AuthoringEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    let current = true;
    estimate({ kind, window_days: 30, ...(improverId ? { improver_agent_id: improverId } : {}) })
      .then((priced) => current && setQuote(priced))
      .catch((failure: unknown) => current && setError(getErrorMessage(failure, tErrors)));
    return () => {
      current = false;
    };
  }, [kind, estimate, tErrors, improverId]);

  async function go() {
    setStarting(true);
    try {
      await start({
        kind,
        window_days: 30,
        ...(improverId ? { improver_agent_id: improverId } : {}),
      });
      onOpenChange(false);
    } catch (failure) {
      setError(getErrorMessage(failure, tErrors));
      setStarting(false);
    }
  }

  const blocked = quote === null || quote.reason !== null || !quote.affordable;
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t(`${kind}.title`)}</DialogTitle>
          <DialogDescription>{t(`${kind}.body`)}</DialogDescription>
        </DialogHeader>
        {quote !== null && quote.reason === null && (
          <p className="text-sm">
            {t("quote", {
              runs: quote.runs,
              ratedDown: quote.rated_down,
              calls: quote.calls,
              cost: usd(quote.estimate_usd, locale),
            })}
          </p>
        )}
        {quote?.reason != null && <p className="text-sm">{t(`reason.${quote.reason}`)}</p>}
        {quote !== null && quote.reason === null && !quote.affordable && (
          <p className="text-destructive text-sm">{t("overBudget")}</p>
        )}
        {error !== null && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <SystemAgentChoice
          kind="improver"
          value={improverId}
          onChange={(value) => {
            setQuote(null);
            setError(null);
            setImproverId(value);
          }}
          disabled={starting}
        />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={blocked || starting} onClick={() => void go()}>
            {t("start")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
