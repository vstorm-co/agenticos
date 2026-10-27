"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement, ImprovementIteration } from "@/types/improvement";
import { useReadOnly } from "./read-only";
import { AttemptSummary } from "./round-results";

/**
 * Which measured attempt the session keeps for accepting, chosen on the result
 * itself. Only a ready session has kept one: a stopped session keeps nothing
 * until somebody chooses, so its preselected attempt still needs the button.
 */
export function AttemptChoice({ session, agent }: { session: Improvement; agent: string }) {
  const t = useTranslations("improvement.keep");
  const tErrors = useTranslations("errors");
  const actions = useImprovement(session.agent_id, session.id);
  const readOnly = useReadOnly();
  const [choice, setChoice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const measured = session.iterations.filter(
    (round) => round.verdict !== null && round.number <= session.max_iterations,
  );
  if (measured.length < 2) return null;
  const choosable = !readOnly && ["ready", "stopped"].includes(session.status);
  const kept = session.status === "ready" ? session.best_iteration_id : null;
  const picked = measured.find((round) => round.id === (choice ?? session.best_iteration_id));
  if (!choosable)
    return (
      <section className="space-y-2">
        <h3 className="text-sm font-medium">{t("title")}</h3>
        <ul className="space-y-2">
          {measured.map((round) => (
            <li
              key={round.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border p-3 text-sm"
            >
              <AttemptSummary session={session} round={round} />
            </li>
          ))}
        </ul>
      </section>
    );
  async function keep(round: ImprovementIteration) {
    setError(null);
    try {
      await actions.selectRound.mutateAsync(round.number);
      setChoice(null);
    } catch (e) {
      setError(getErrorMessage(e, tErrors));
    }
  }
  const pending = picked && picked.id !== kept ? picked : undefined;
  const risky = pending !== undefined && pending.verdict !== "better";
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2 text-sm font-medium">{t("title")}</legend>
      {measured.map((round) => (
        <label
          key={round.id}
          className="has-[:checked]:border-foreground has-[:checked]:bg-muted flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border p-3 text-sm"
        >
          <input
            type="radio"
            name={`keep-${session.id}`}
            value={round.id}
            checked={picked?.id === round.id}
            onChange={() => {
              setError(null);
              setChoice(round.id);
            }}
            aria-label={t("option", { number: round.number })}
            className="accent-foreground"
          />
          <AttemptSummary session={session} round={round} />
        </label>
      ))}
      {pending && (
        <div className="space-y-2 pt-1">
          {risky && <NotBetterWarning round={pending} agent={agent} />}
          <Button
            variant={risky ? "outline" : "default"}
            disabled={actions.selectRound.isPending}
            onClick={() => void keep(pending)}
          >
            {t(risky ? "keepAnyway" : "keep", { number: pending.number })}
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </fieldset>
  );
}

/** What keeping an attempt that was not better costs: the questions it broke, or no gain. */
export function NotBetterWarning({ round, agent }: { round: ImprovementIteration; agent: string }) {
  const t = useTranslations("improvement.keep");
  const broken = Number(round.verdict_detail?.broken ?? 0);
  return (
    <p role="status" className="text-warning text-sm">
      {round.verdict === "regression" && broken > 0
        ? t("broke", { number: round.number, broken, agent })
        : t("notBetter", { number: round.number, agent })}
    </p>
  );
}
