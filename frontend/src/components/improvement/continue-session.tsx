"use client";

import { type ReactNode, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, ConfirmDialog, Input, Label, Textarea } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { ContinuationEstimate, Improvement } from "@/types/improvement";

type Variant = "default" | "outline" | "ghost";

/** The longest note the server keeps for a new attempt's helper. */
const NOTE_LIMIT = 2000;

/**
 * Whether another paid attempt may start: a failed or over-budget step resumes,
 * as does a step stopped for lost access, under whoever presses it,
 * and a measured session tries again, when a person asks, while it has attempts
 * left. Attempts that keep changing nothing only earn a hint, never a refusal.
 */
export function continuation(session: Improvement) {
  const resume =
    (session.status === "failed" && ["proposing", "evaluating"].includes(session.stage ?? "")) ||
    (session.status === "stopped" &&
      session.stop_reason === "budget" &&
      ["classifying", "drafting", "proposing", "evaluating"].includes(session.stage ?? "")) ||
    (session.status === "stopped" && session.stop_reason === "permission");
  const measured = session.iterations.filter((r) => r.verdict !== null);
  const last = measured.at(-1);
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
    session.iteration < session.max_iterations &&
    !["no_data", "knowledge_only", "repeat_candidate", "max_iterations", "stale"].includes(
      session.stop_reason ?? "",
    );
  const own = session.can_restart !== false;
  const canContinue = own && (resume || next);
  const primary = last?.verdict === "regression" || resume;
  return { resume, canContinue, own, primary };
}

/** A continuation is a new priced decision, with the original source and round bounds. */
export function ContinueSession({
  session,
  lead,
  trail,
  emphasis,
  onStarted,
}: {
  session: Improvement;
  /** A decision shown first in the same row, so the screen has one row of actions. */
  lead?: ReactNode;
  trail?: ReactNode;
  /**
   * Set inside the result's decision card, which ranks the actions itself: trying
   * again is offered only when it can start, and discarding reads as ending the session.
   */
  emphasis?: { again: Variant; end: Variant };
  onStarted: () => void;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const actions = useImprovement(session.agent_id, session.id);
  const [open, setOpen] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [budget, setBudget] = useState(session.budget_usd);
  const [note, setNote] = useState("");
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
  const { resume, canContinue, own, primary } = continuation(session);
  // A note steers a new attempt's helper; a resumed or retried step repeats one already written.
  const attempt = !resume && session.status !== "failed";
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
    <section className={emphasis ? "space-y-4" : "space-y-4 rounded-xl border p-4 sm:p-6"}>
      <div className="flex flex-wrap gap-3">
        {lead}
        {(!emphasis || canContinue) && (
          <Button
            className="h-auto min-h-9 whitespace-normal"
            variant={emphasis?.again ?? (primary ? "default" : "outline")}
            disabled={!canContinue || actions.continueSession.isPending}
            onClick={() => setOpen((value) => !value)}
          >
            {t(
              session.status === "failed"
                ? "retryStep"
                : session.stop_reason === "permission"
                  ? "resumeWithMyAccess"
                  : resume
                    ? "raiseBudgetContinue"
                    : emphasis
                      ? "resultDecision.tryAgain"
                      : "improveAgain",
            )}
          </Button>
        )}
        {session.can_discard !== false && (
          <Button
            variant={emphasis?.end ?? "ghost"}
            disabled={actions.discard.isPending}
            onClick={() => setDiscarding(true)}
          >
            {t(emphasis ? "resultDecision.end" : "discard")}
          </Button>
        )}
        {trail}
      </div>
      {!own ? (
        <p className="text-muted-foreground text-sm">{t("paidRestartOwner")}</p>
      ) : (
        !canContinue &&
        !emphasis && <p className="text-muted-foreground text-sm">{t("continuationStopped")}</p>
      )}
      {open && canContinue && (
        <div className="max-w-xl space-y-3">
          <p className="text-muted-foreground text-sm">{t("continuationBody")}</p>
          {attempt && (
            <div className="space-y-2">
              <Label htmlFor="continuation-note">{t("helperNote")}</Label>
              <Textarea
                id="continuation-note"
                maxLength={NOTE_LIMIT}
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <p className="text-muted-foreground text-xs">{t("helperNoteHint")}</p>
            </div>
          )}
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
                    await actions.continueSession.mutateAsync({
                      ...quote,
                      ...(attempt && note.trim() ? { note: note.trim() } : {}),
                    });
                    setQuoted(null);
                    setNote("");
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
