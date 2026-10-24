"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, ConfirmDialog, Input, Label } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { ContinuationEstimate, Improvement } from "@/types/improvement";

/** A continuation is a new priced decision, with the original source and round bounds. */
export function ContinueSession({
  session,
  onStarted,
}: {
  session: Improvement;
  onStarted: () => void;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const actions = useImprovement(session.agent_id, session.id);
  const [open, setOpen] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [budget, setBudget] = useState(session.budget_usd);
  const [quoted, setQuoted] = useState<{ key: string; value: ContinuationEstimate } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify([
    budget,
    session.status,
    session.stage,
    session.iteration,
    session.max_iterations,
    session.spent_usd,
    session.iterations.map((r) => [
      r.id,
      r.candidate_spec_hash,
      r.verdict,
      r.verdict_detail,
      r.eval_run_ids,
    ]),
  ]);
  const quote = quoted?.key === key ? quoted.value : null;
  const waiting = ["ready", "stopped", "failed"].includes(session.status);
  const resume =
    (session.status === "failed" && ["proposing", "evaluating"].includes(session.stage ?? "")) ||
    (session.status === "stopped" &&
      session.stop_reason === "budget" &&
      ["classifying", "drafting", "proposing", "evaluating"].includes(session.stage ?? ""));
  const measured = session.iterations.filter((r) => r.verdict !== null);
  const last = measured.at(-1);
  const previous = measured.at(-2);
  const noProgress = last?.verdict === "no_change" && previous?.verdict === "no_change";
  const used = Math.max(
    0,
    ...session.iterations
      .filter((r) => r.authoring_request_id || r.eval_run_ids.length || r.verdict)
      .map((r) => r.number),
  );
  const next =
    ["ready", "stopped"].includes(session.status) &&
    measured.length > 0 &&
    used < session.max_iterations &&
    !noProgress &&
    last?.verdict !== "inconclusive" &&
    ![
      "no_data",
      "knowledge_only",
      "repeat_candidate",
      "inconclusive",
      "max_iterations",
      "permission",
      "stale",
    ].includes(session.stop_reason ?? "");
  const own = session.can_restart !== false;
  const canContinue = own && (resume || next);
  const primary = last?.verdict === "regression" || resume;
  async function act(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(getErrorMessage(e, tErrors));
    }
  }
  if (!waiting) return null;
  return (
    <section className="space-y-4 rounded-xl border p-4 sm:p-6">
      <div className="flex flex-wrap gap-3">
        <Button
          className="h-auto min-h-9 whitespace-normal"
          variant={primary ? "default" : "outline"}
          disabled={!canContinue || actions.continueSession.isPending}
          onClick={() => setOpen((value) => !value)}
        >
          {t(
            session.status === "failed"
              ? "retryStep"
              : resume
                ? "raiseBudgetContinue"
                : "improveAgain",
          )}
        </Button>
        {session.can_discard !== false && (
          <Button
            variant="ghost"
            disabled={actions.discard.isPending}
            onClick={() => setDiscarding(true)}
          >
            {t("discard")}
          </Button>
        )}
      </div>
      {!own ? (
        <p className="text-muted-foreground text-sm">{t("paidRestartOwner")}</p>
      ) : (
        !canContinue && <p className="text-muted-foreground text-sm">{t("continuationStopped")}</p>
      )}
      {open && canContinue && (
        <div className="max-w-xl space-y-3">
          <p className="text-muted-foreground text-sm">{t("continuationBody")}</p>
          <Label htmlFor="continuation-budget">{t("budget")}</Label>
          <Input
            id="continuation-budget"
            type="number"
            min="0.000001"
            step="0.01"
            value={budget}
            onChange={(event) => setBudget(event.target.value)}
          />
          <Button
            variant="outline"
            className="h-auto min-h-9 whitespace-normal"
            disabled={
              !Number.isFinite(Number(budget)) ||
              Number(budget) <= 0 ||
              actions.estimateContinuation.isPending
            }
            onClick={() =>
              void act(async () => {
                const value = await actions.estimateContinuation.mutateAsync(budget);
                setQuoted({ key, value });
              })
            }
          >
            {t("estimateContinuation")}
          </Button>
          {quote && (
            <div className="space-y-3 text-sm">
              <p>
                {t("continuationQuote", {
                  number: quote.number,
                  max: session.max_iterations,
                  cost: usd(quote.total_usd, locale),
                })}
              </p>
              {!quote.affordable && <p>{t("continuationUnaffordable")}</p>}
              <Button
                className="h-auto min-h-9 whitespace-normal"
                disabled={!quote.affordable || actions.continueSession.isPending}
                onClick={() =>
                  void act(async () => {
                    await actions.continueSession.mutateAsync(quote);
                    setQuoted(null);
                    setOpen(false);
                    onStarted();
                  })
                }
              >
                {t("confirmContinuation")}
              </Button>
            </div>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title={t("discardTitle")}
        description={
          <>
            {t("discardBody")}
            {error && (
              <span role="alert" className="text-destructive mt-2 block">
                {error}
              </span>
            )}
          </>
        }
        confirmLabel={t("confirmDiscard")}
        loading={actions.discard.isPending}
        onConfirm={() =>
          act(async () => {
            await actions.discard.mutateAsync();
            setDiscarding(false);
            onStarted();
          })
        }
      />
    </section>
  );
}
