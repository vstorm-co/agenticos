"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, CircleDot, Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { usd } from "@/components/evals/format";
import { Button } from "@/components/ui";
import { WizardSteps } from "@/components/ui/wizard-steps";
import { useAttemptChanges, useImprovement } from "@/hooks/use-improvements";
import { useUrlState } from "@/hooks/use-url-state";
import { getErrorMessage } from "@/lib/api-error";
import {
  ATTEMPT_RESULT_REASONS,
  IMPROVEMENT_STEPS as STEPS,
  currentAttempt,
  currentImprovementStep,
  improvementSteps,
  isActive,
  isMerge,
  isReachable,
  stopOf,
  type ImprovementStep as Step,
  type ImprovementStepView,
} from "@/lib/improvement-steps";
import { subjectOf } from "@/lib/improvement-subject";
import type { ContinuationEstimate, Improvement } from "@/types/improvement";
import { ContinueSession } from "./continue-session";
import { EndSession } from "./end-session";
import { NextStep } from "./next-step";
import { ReadOnlyNote, ReadOnlyProvider, type ReadOnlyReason } from "./read-only";
import { StepDecisions } from "./step-decisions";

/** Steps the wizard used to have, and the one that holds what they showed. */
const RETIRED_STEPS: Record<string, Step> = { today: "check", testSet: "understand" };

/**
 * Next step at a stop, as a session that does not choose proposed changes words it: a
 * merge says what to settle first and what its check also asks.
 */
export interface NextStepTerms {
  hint?: string;
  /** Why the step waits; it is not priced until this clears, since it changes what is measured. */
  blocked?: string;
  body?: Record<string, unknown>;
  /** Changes with each edit of what the step measures, so it is priced again. */
  revision?: string | null;
}

/** What a step's panel can do to the frame around it. */
export interface ShellNav {
  step: Step;
  current: Step;
  views: Record<Step, ImprovementStepView>;
  goTo: (target: Step) => void;
  followCurrent: () => void;
  /** Runs a write, saying under the steps what refused it. */
  act: (action: () => Promise<void>) => Promise<void>;
}

/**
 * The frame every improvement session is drawn in, whatever it improves: where the
 * session stands, the five steps, Next step at a stop, Try again, and the way out.
 *
 * What each step shows is the caller's, through `panel`; an agent's session and a
 * skill's differ there and nowhere else.
 */
export function ImprovementShell({
  session,
  readOnly,
  closeHref,
  panel,
  wordingOpen = false,
  nextStepDetail,
  nextStep,
  footer,
  onRestart,
}: {
  session: Improvement;
  readOnly: ReadOnlyReason | null;
  /** Where Close leads: the agent, or the skill. */
  closeHref: string;
  panel: (nav: ShellNav) => ReactNode;
  /** A reworded change not saved yet holds Next step at the Changes stop. */
  wordingOpen?: boolean;
  /** What a priced next step will do, under its price. */
  nextStepDetail?: (quote: ContinuationEstimate) => ReactNode;
  /** In place of the hint and the hold that read the proposed changes, for a merge. */
  nextStep?: NextStepTerms;
  /** Said under the step's panel, above Try again. */
  footer?: ReactNode;
  /** After a new attempt starts from Try again or a result. */
  onRestart?: () => void;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const actions = useImprovement(subjectOf(session), session.id);
  // Without ?step= the screen follows the session; a person who opens another step
  // stays there, and can link to it, until they go back to the current one.
  const [stepParam, setStepParam] = useUrlState("step");
  // Older links name steps the wizard no longer has; they open the step that took
  // over their content.
  const retired = stepParam ? RETIRED_STEPS[stepParam] : undefined;
  useEffect(() => {
    if (retired) setStepParam(retired);
  }, [retired, setStepParam]);
  const [moves, setMoves] = useState(0);
  const content = useRef<HTMLDivElement>(null);
  // A screen read aloud starts at its heading, not at the step button just pressed.
  useEffect(() => {
    if (moves === 0) return;
    const heading = content.current?.querySelector<HTMLElement>("h2, h3");
    if (!heading) return;
    heading.tabIndex = -1;
    heading.focus();
  }, [moves]);
  const [error, setError] = useState<string | null>(null);
  const atChanges = stopOf(session) === "changes" && !isMerge(session);
  const proposed = useAttemptChanges(subjectOf(session), session.id, session.iteration, {
    enabled: atChanges,
  });
  async function act(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(getErrorMessage(e, tErrors));
    }
  }
  const current = currentImprovementStep(session);
  const views = improvementSteps(session);
  const picked = STEPS.find((id) => id === (retired ?? stepParam));
  const step = picked && isReachable(views[picked]) ? picked : current;
  const active = isActive(session);
  const working = STEPS.some((id) => views[id].state === "running");
  const attempt = currentAttempt(session);
  function goTo(target: Step) {
    setStepParam(target === current ? null : target);
    setMoves((count) => count + 1);
  }
  function followCurrent() {
    goTo(current);
  }
  const reachable = STEPS.filter((id) => isReachable(views[id]));
  const previous = reachable.filter((id) => STEPS.indexOf(id) < STEPS.indexOf(step)).at(-1);
  const next = reachable.find((id) => STEPS.indexOf(id) > STEPS.indexOf(step));
  const missingHeldOut = Number(session.iterations[0]?.verdict_detail?.missing_holdout ?? 0);
  return (
    <ReadOnlyProvider value={readOnly}>
      <div className="space-y-6">
        <SessionLine session={session} working={working} />
        <nav
          data-tour="improvement-steps"
          aria-label={t("stepsLabel")}
          className="bg-card sticky top-0 z-20 rounded-xl border p-4 shadow-sm sm:p-5"
        >
          <WizardSteps
            responsive
            steps={STEPS.map((id) => ({
              id,
              label: t(`steps.${id}`),
              status: views[id].state,
              statusLabel:
                id === "accept" && session.status === "rejected"
                  ? t("stepState.ended")
                  : t(`stepState.${views[id].state}`),
              tourId: `improvement-step-${id}`,
              disabled: !isReachable(views[id]),
            }))}
            current={step}
            onSelect={(id) => {
              const target = STEPS.find((item) => item === id);
              if (target) goTo(target);
            }}
          />
          {step !== current && (
            <button
              type="button"
              className="mt-2 text-sm underline underline-offset-4"
              onClick={followCurrent}
            >
              {t("goToCurrent")}
            </button>
          )}
        </nav>
        <ReadOnlyNote />
        {session.stop_reason && step !== "result" && (
          <p role={session.status === "failed" ? "alert" : undefined} className="text-sm">
            {session.stop_reason === "no_data" && missingHeldOut > 0
              ? t("tooFewHeldOut", { needed: missingHeldOut })
              : t(`stop.${session.stop_reason}`)}
          </p>
        )}
        {session.error && (
          <details className="text-muted-foreground text-sm">
            <summary className="cursor-pointer">{t("technicalDetails")}</summary>
            <p className="mt-2 break-words">{session.error}</p>
          </details>
        )}
        <div
          ref={content}
          data-step-panel
          className="bg-card min-w-0 space-y-6 rounded-2xl border p-4 sm:p-6 [&_h2]:scroll-mt-40 [&_h3]:scroll-mt-40"
        >
          {panel({ step, current, views, goTo, followCurrent, act })}
          {step === stopOf(session) && (
            <NextStep
              session={session}
              detail={nextStepDetail}
              hint={
                nextStep
                  ? nextStep.hint
                  : step === "changes" &&
                      proposed.changes.filter(
                        (hunk) => !attempt?.dropped_hunk_ids.includes(hunk.id),
                      ).length === 1
                    ? t("nextUp.hintSingle")
                    : undefined
              }
              blocked={
                nextStep
                  ? nextStep.blocked
                  : step !== "changes"
                    ? undefined
                    : wordingOpen
                      ? t("nextUp.saveWordingFirst")
                      : !attempt?.included_hunk_ids?.length
                        ? t("selectSomeChanges")
                        : undefined
              }
              body={nextStep?.body}
              hold={Boolean(nextStep?.blocked)}
              revision={nextStep?.revision}
              onStarted={followCurrent}
            />
          )}
          <StepDecisions session={session} step={step} />
        </div>
        {footer}
        {readOnly === null &&
          step !== "result" &&
          (session.status === "failed" || session.stop_reason === "budget") && (
            <ContinueSession
              session={session}
              onStarted={() => {
                followCurrent();
                onRestart?.();
              }}
            />
          )}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          {previous ? (
            <Button variant="outline" onClick={() => goTo(previous)}>
              <ChevronLeft className="h-4 w-4" aria-hidden />
              {t("previousStep")}
            </Button>
          ) : (
            <span />
          )}
          {next && step !== "result" && step !== "accept" && (
            <Button variant="outline" onClick={() => goTo(next)}>
              {t("nextStep")}
              <ChevronRight className="h-4 w-4" aria-hidden />
            </Button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {(active || session.status === "failed") && readOnly === null && (
            <Button
              variant="outline"
              disabled={actions.cancel.isPending}
              onClick={() =>
                void act(async () => {
                  await actions.cancel.mutateAsync();
                })
              }
            >
              {t("stopAction")}
            </Button>
          )}
          {readOnly === null &&
            ["waiting", "ready", "stopped"].includes(session.status) &&
            step !== "result" &&
            session.stop_reason !== "budget" && <EndSession session={session} />}
          <Link className="text-sm underline" href={closeHref}>
            {t("close")}
          </Link>
        </div>
        {error && (
          <p role="alert" className="text-destructive-ink text-sm">
            {error}
          </p>
        )}
      </div>
    </ReadOnlyProvider>
  );
}

/** The session's state and spend in one line above the steps, on every step alike. */
function SessionLine({ session, working }: { session: Improvement; working: boolean }) {
  const t = useTranslations("improvement");
  const stop = stopOf(session);
  const locale = useLocale();
  const finishedAttempt =
    session.status === "stopped" && ATTEMPT_RESULT_REASONS.includes(session.stop_reason ?? "");
  const used = Math.min(
    100,
    Math.round((Number(session.spent_usd) / Math.max(Number(session.budget_usd), 1e-9)) * 100),
  );
  return (
    <section
      aria-label={t("sessionLine")}
      className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
    >
      <span role="status" className="text-foreground inline-flex items-center gap-1.5">
        {working ? (
          <Loader2 className="text-chart size-3.5 animate-spin" aria-hidden />
        ) : (
          <CircleDot className="size-3.5" aria-hidden />
        )}
        {working
          ? t("status.running")
          : stop
            ? t(`waitingFor.${stop}`)
            : t(`status.${finishedAttempt ? "attemptFinished" : session.status}`)}
      </span>
      <span aria-hidden>·</span>
      <span>
        {t("spend", {
          spent: usd(session.spent_usd, locale),
          budget: usd(session.budget_usd, locale),
        })}
      </span>
      <span
        role="meter"
        aria-label={t("budgetUsed")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={used}
        className="bg-muted h-1 w-12 overflow-hidden rounded-full"
      >
        <span className="bg-chart block h-full rounded-full" style={{ width: `${used}%` }} />
      </span>
    </section>
  );
}

/** A step's panel while its work is in progress. */
export function WorkingNote({ children }: { children: ReactNode }) {
  return (
    <p
      role="status"
      className="text-muted-foreground flex items-center gap-2 rounded-xl border p-6 text-sm"
    >
      <Loader2 className="text-chart size-4 shrink-0 animate-spin" aria-hidden />
      {children}
    </p>
  );
}
