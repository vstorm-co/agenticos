"use client";
import { type ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, CircleDot, Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { WizardSteps } from "@/components/ui/wizard-steps";
import { usd } from "@/components/evals/format";
import { ChangeSelection } from "./change-selection";
import { useAgent } from "@/hooks/use-agents";
import { useAgentAuthoring } from "@/hooks/use-authoring";
import { useAttemptChanges, useImprovement } from "@/hooks/use-improvements";
import { useUrlState } from "@/hooks/use-url-state";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { useOrgStore } from "@/stores/org-store";
import type { Improvement } from "@/types/improvement";
import { Perm } from "@/types/permissions";
import { ContinueSession } from "./continue-session";
import { StartSession } from "./start-session";
import { KnowledgeDrafts } from "./knowledge-drafts";
import { TestQuestions } from "./session-inputs";
import { Understand } from "./understand";
import { AttemptChanges } from "./attempt-changes";
import { AttemptHistory } from "./attempt-history";
import { CheckProgress } from "./check-progress";
import { AcceptedChanges, TriedChanges } from "./tried-changes";
import { EndSession } from "./end-session";
import { NextStep } from "./next-step";
import { StepDecisions } from "./step-decisions";
import { NotBetterWarning } from "./attempt-choice";
import { AcceptSummary, GuardNote, KnowledgeDocuments } from "./outcome";
import { ResultStep } from "./result-decision";
import { ReadOnlyNote, ReadOnlyProvider, type ReadOnlyReason } from "./read-only";
import { SessionDecision } from "./session-decision";

import {
  ATTEMPT_RESULT_REASONS,
  IMPROVEMENT_STEPS as STEPS,
  currentAttempt,
  currentImprovementStep,
  hasCandidate,
  improvementSteps,
  isActive,
  isClosed,
  isReachable,
  stopOf,
  type ImprovementStep as Step,
} from "@/lib/improvement-steps";
/** Steps the wizard used to have, and the one that holds what they showed. */
const RETIRED_STEPS: Record<string, Step> = { today: "check", testSet: "understand" };

export function ImprovementPage({ agentId, sessionId }: { agentId: string; sessionId: string }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { agent, isLoading, error } = useAgent(agentId);
  const { can } = usePermissions();
  if (isLoading) return <LoadingState variant="skeleton-cards" rows={3} />;
  if (error || !agent) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  // Reading a session needs the agent and its runs; starting one, or changing
  // one, needs edit access too, and without it the session is only read.
  if (!can(Perm.runsView) || (!agent.can_edit && sessionId === "new"))
    return (
      <div className="mx-auto w-full max-w-5xl space-y-6 pb-16">
        <PageHeader
          title={t("title", { name: agent.name })}
          breadcrumbs={[{ label: agent.name, href: `/agents/${agentId}` }, { label: t("heading") }]}
        />
        <p role="alert">{t("permission")}</p>
        <Link className="text-sm underline underline-offset-4" href={`/agents/${agentId}`}>
          {t("openAgent")}
        </Link>
      </div>
    );
  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 pb-16">
      <PageHeader
        title={t("title", { name: agent.name })}
        breadcrumbs={[{ label: agent.name, href: `/agents/${agentId}` }, { label: t("heading") }]}
      />
      {sessionId === "new" ? (
        <StartSession key={`${orgId}:${agentId}`} agentId={agentId} />
      ) : (
        <Session
          key={`${orgId}:${agentId}:${sessionId}`}
          agentId={agentId}
          sessionId={sessionId}
          agentName={agent.name}
          canPublish={agent.can_publish === true}
          canEdit={agent.can_edit === true}
        />
      )}
    </div>
  );
}
function Session({
  agentId,
  sessionId,
  agentName,
  canPublish,
  canEdit,
}: {
  agentId: string;
  sessionId: string;
  agentName: string;
  canPublish: boolean;
  canEdit: boolean;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const actions = useImprovement(agentId, sessionId);
  const authoringQuery = useAgentAuthoring(agentId);
  const { authoring } = authoringQuery;
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
  const [automaticChoice, setAutomatic] = useState<boolean | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [draftSelection, setDraftSelection] = useState<{ roundId: string; ids: string[] } | null>(
    null,
  );
  const [wordingOpen, setWordingOpen] = useState(false);
  const atChanges = actions.session ? stopOf(actions.session) === "changes" : false;
  const proposed = useAttemptChanges(agentId, sessionId, actions.session?.iteration ?? 1, {
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
  const session = actions.session;
  if (actions.isLoading) return <LoadingState variant="skeleton-cards" rows={3} />;
  if (actions.error || !session)
    return (
      <ErrorState
        description={getErrorMessage(actions.error, tErrors)}
        cta={{ label: t("retryRead"), onClick: () => void actions.refetch() }}
      />
    );
  const readOnly: ReadOnlyReason | null = isClosed(session)
    ? "finished"
    : canEdit
      ? null
      : "viewOnly";
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
  const chosen = session.iterations.find((r) => r.id === session.best_iteration_id);
  const gain = chosen?.verdict === "better";
  // Without a measured gain nothing is pressed on the person: no standing check, no publish first.
  const automatic = automaticChoice ?? gain;
  const selectedBatch = authoring?.batch?.id === chosen?.batch_id ? authoring?.batch : null;
  const measuredIds =
    chosen?.included_hunk_ids ??
    selectedBatch?.hunks.filter((h) => h.status === "pending").map((h) => h.id) ??
    [];
  const included =
    draftSelection && draftSelection.roundId === chosen?.id ? draftSelection.ids : measuredIds;
  const selectionDirty =
    JSON.stringify([...included].sort()) !== JSON.stringify([...measuredIds].sort());
  const missingBatch = !selectedBatch;
  const missingHeldOut = Number(session.iterations[0]?.verdict_detail?.missing_holdout ?? 0);
  const blockedChanges = selectedBatch?.hunks.some(
    (hunk) => hunk.status === "pending" && measuredIds.includes(hunk.id) && hunk.blocked !== null,
  );
  const knowledgeCheck = <KnowledgeDrafts session={session} />;
  return (
    <ReadOnlyProvider value={readOnly}>
      <div className="space-y-6">
        <SessionLine session={session} working={working} />
        <nav data-tour="improvement-steps" aria-label={t("stepsLabel")}>
          <WizardSteps
            responsive
            steps={STEPS.map((id) => ({
              id,
              label: t(`steps.${id}`),
              status: views[id].state,
              statusLabel: t(`stepState.${views[id].state}`),
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
        <div ref={content} data-step-panel className="space-y-6">
          {step === "understand" &&
            (views.understand.content === "working" ? (
              <WorkingNote>{t("understandWorking")}</WorkingNote>
            ) : (
              <>
                <Understand session={session} />
                <TestQuestions session={session} />
              </>
            ))}
          {step === "changes" && (
            <section className="grid gap-6 md:grid-cols-[2fr_1fr]" data-tour="improvement-changes">
              {stopOf(session) === "changes" ? (
                <section className="min-w-0 space-y-4">
                  <AttemptHistory session={session} />
                  <h2 className="font-medium">
                    {t("round", { number: session.iteration, max: session.max_iterations })}
                  </h2>
                  {session.iteration > 1 && (
                    <p className="text-muted-foreground text-sm">{t("freshAttempt")}</p>
                  )}
                  <AttemptChanges
                    session={session}
                    editable={!readOnly}
                    onEditing={setWordingOpen}
                  />
                </section>
              ) : chosen && selectedBatch?.hunks.length && !isClosed(session) ? (
                <ChangeSelection
                  session={session}
                  round={chosen}
                  hunks={selectedBatch.hunks}
                  included={included}
                  onChange={(ids) => setDraftSelection({ roundId: chosen.id, ids })}
                  onStarted={() => {
                    setDraftSelection(null);
                    followCurrent();
                    setConfirm(false);
                  }}
                />
              ) : active ? (
                <section className="min-w-0 space-y-4">
                  <AttemptHistory session={session} />
                  {views.changes.content === "working" ? (
                    <WorkingNote>
                      {session.iteration > 1
                        ? t("writingAgain", {
                            number: session.iteration,
                            max: session.max_iterations,
                          })
                        : t("changesWorking")}
                    </WorkingNote>
                  ) : (
                    <>
                      <h2 className="font-medium">
                        {t("checkingChanges", {
                          number: session.iteration,
                          max: session.max_iterations,
                        })}
                      </h2>
                      <AttemptChanges session={session} editable={false} />
                    </>
                  )}
                </section>
              ) : session.iterations.some((round) => round.batch_id) ? (
                <TriedChanges session={session} />
              ) : (
                <section className="space-y-3 rounded-xl border p-6 text-sm">
                  <p>{t("noChangesFound")}</p>
                  <ul className="list-disc space-y-1 pl-5">
                    {session.iterations.map((round) => (
                      <li key={round.id}>
                        {round.number > session.max_iterations
                          ? t("heldBack")
                          : t("triedAttempt", {
                              number: round.number,
                              verdict: round.verdict ?? (round.batch_id ? "unmeasured" : "none"),
                              dropped: round.dropped.length,
                            })}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <KnowledgeDocuments session={session} />
            </section>
          )}
          {step === "check" && (
            <CheckProgress session={session} onShowResult={() => goTo("result")} />
          )}
          {step === "result" && (
            <ResultStep
              session={session}
              agent={agentName}
              candidate={hasCandidate(session)}
              canAccept={!selectionDirty && !missingBatch}
              knowledgeCheck={knowledgeCheck}
              onAccept={() => goTo("accept")}
              onStarted={() => {
                followCurrent();
                setDraftSelection(null);
                setConfirm(false);
              }}
            />
          )}
          {step === "accept" && isClosed(session) && <SessionDecision session={session} />}
          {step === "accept" && !isClosed(session) && (
            <section className="space-y-4 rounded-xl border p-6" data-tour="improvement-accept">
              <h2 className="font-medium">{t("steps.accept")}</h2>
              <AcceptSummary session={session} round={chosen} />
              {chosen && !gain && <NotBetterWarning round={chosen} agent={agentName} />}
              {chosen && session.status === "ready" && (
                <AcceptedChanges session={session} round={chosen} />
              )}
              {session.status === "ready" && <KnowledgeDocuments session={session} accept />}
              {session.status === "ready" && readOnly === null && (
                <>
                  {missingBatch &&
                    (authoringQuery.error ? (
                      <ErrorState
                        description={getErrorMessage(authoringQuery.error, tErrors)}
                        cta={{
                          label: t("retryRead"),
                          onClick: () => void authoringQuery.refetch(),
                        }}
                      />
                    ) : (
                      <p role="status" className="text-sm">
                        {t(authoringQuery.isLoading ? "changesPending" : "changesReplaced")}
                      </p>
                    ))}
                  {blockedChanges && (
                    <p role="alert" className="text-warning text-sm">
                      {t("blockedChanges")}
                    </p>
                  )}
                  {session.offer_automatic_check && (
                    <label
                      className="flex items-start gap-2 text-sm"
                      data-tour="improvement-automatic-check"
                    >
                      <input
                        type="checkbox"
                        checked={automatic}
                        onChange={(e) => setAutomatic(e.target.checked)}
                      />
                      {t("automatic")}
                    </label>
                  )}
                  {canPublish && session.next_version != null && (
                    <div className="space-y-1" data-tour="improvement-guard">
                      <GuardNote agentId={agentId} version={session.next_version} />
                    </div>
                  )}
                  {!canPublish && (
                    <p className="text-muted-foreground text-sm">{t("publishNeedsPermission")}</p>
                  )}
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={confirm}
                      onChange={(e) => setConfirm(e.target.checked)}
                    />
                    {t("confirmation")}
                  </label>
                  <div className="flex flex-wrap gap-3">
                    <Button
                      variant={gain || !canPublish ? "outline" : "default"}
                      disabled={
                        !confirm ||
                        missingBatch ||
                        selectionDirty ||
                        blockedChanges ||
                        actions.finish.isPending
                      }
                      onClick={() =>
                        void act(async () => {
                          await actions.finish.mutateAsync({
                            confirmed: true,
                            publish: false,
                            automatic_check: session.offer_automatic_check === true && automatic,
                          });
                        })
                      }
                    >
                      {t("keepDraft")}
                    </Button>
                    {canPublish && (
                      <Button
                        variant={gain ? "default" : "outline"}
                        disabled={
                          !confirm ||
                          missingBatch ||
                          selectionDirty ||
                          blockedChanges ||
                          actions.finish.isPending
                        }
                        onClick={() =>
                          void act(async () => {
                            await actions.finish.mutateAsync({
                              confirmed: true,
                              publish: true,
                              automatic_check: session.offer_automatic_check === true && automatic,
                            });
                          })
                        }
                      >
                        {session.next_version == null
                          ? t("publish")
                          : t("publishVersion", { version: session.next_version })}
                      </Button>
                    )}
                  </div>
                </>
              )}
              <Link className="block text-sm underline" href={`/agents/${agentId}`}>
                {t("openAgent")}
              </Link>
            </section>
          )}
          {step === stopOf(session) && (
            <NextStep
              session={session}
              hint={
                step === "changes" &&
                proposed.changes.filter((hunk) => !attempt?.dropped_hunk_ids.includes(hunk.id))
                  .length === 1
                  ? t("nextUp.hintSingle")
                  : undefined
              }
              blocked={
                step !== "changes"
                  ? undefined
                  : wordingOpen
                    ? t("nextUp.saveWordingFirst")
                    : !attempt?.included_hunk_ids?.length
                      ? t("selectSomeChanges")
                      : undefined
              }
              onStarted={followCurrent}
            />
          )}
          <StepDecisions session={session} step={step} />
        </div>
        {selectionDirty && readOnly === null && (
          <p role="alert" className="text-sm">
            {t("selectionNeedsCheck")}
          </p>
        )}
        {readOnly === null &&
          step !== "result" &&
          (session.status === "failed" || session.stop_reason === "budget") && (
            <ContinueSession
              session={session}
              onStarted={() => {
                followCurrent();
                setDraftSelection(null);
                setConfirm(false);
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
          <Link className="text-sm underline" href={`/agents/${agentId}`}>
            {t("close")}
          </Link>
        </div>
        {error && (
          <p role="alert" className="text-destructive text-sm">
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
function WorkingNote({ children }: { children: ReactNode }) {
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
