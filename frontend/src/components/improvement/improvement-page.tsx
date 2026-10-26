"use client";
import { useEffect, useRef, useState } from "react";
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
import { useImprovement } from "@/hooks/use-improvements";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { useOrgStore } from "@/stores/org-store";
import { Perm } from "@/types/permissions";
import { ContinueSession } from "./continue-session";
import { StartSession } from "./start-session";
import { KnowledgeDrafts } from "./knowledge-drafts";
import { RoundResults, RoundHistory } from "./round-results";
import { TestQuestions, Today } from "./session-inputs";
import { Understand } from "./understand";
import { CheckProgress } from "./check-progress";
import { StepDecisions } from "./step-decisions";
import { AcceptSummary, DoneScreen, GuardNote, KnowledgeDocuments, ResultSummary } from "./outcome";

import {
  IMPROVEMENT_STEPS as STEPS,
  currentImprovementStep,
  improvementStepStates,
  type ImprovementStep as Step,
} from "@/lib/improvement-steps";
export function ImprovementPage({ agentId, sessionId }: { agentId: string; sessionId: string }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { agent, isLoading, error } = useAgent(agentId);
  const { can } = usePermissions();
  if (isLoading) return <LoadingState variant="skeleton-cards" rows={3} />;
  if (error || !agent) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  if (!agent.can_edit || !can(Perm.runsView))
    return (
      <div className="mx-auto max-w-5xl space-y-6 pb-16">
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
    <div className="mx-auto max-w-5xl space-y-6 pb-16">
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
          canPublish={agent.can_publish === true}
        />
      )}
    </div>
  );
}
function Session({
  agentId,
  sessionId,
  canPublish,
}: {
  agentId: string;
  sessionId: string;
  canPublish: boolean;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const actions = useImprovement(agentId, sessionId);
  const authoringQuery = useAgentAuthoring(agentId);
  const { authoring } = authoringQuery;
  const [selected, setSelected] = useState<Step | null>(null);
  const content = useRef<HTMLDivElement>(null);
  // A screen read aloud starts at its heading, not at the step button just pressed.
  useEffect(() => {
    if (selected === null) return;
    const heading = content.current?.querySelector<HTMLElement>("h2, h3");
    if (!heading) return;
    heading.tabIndex = -1;
    heading.focus();
  }, [selected]);
  const [error, setError] = useState<string | null>(null);
  const [automatic, setAutomatic] = useState(true);
  const [confirm, setConfirm] = useState(false);
  const [draftSelection, setDraftSelection] = useState<{ roundId: string; ids: string[] } | null>(
    null,
  );
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
  const current = currentImprovementStep(session);
  const states = improvementStepStates(session);
  const step = selected ?? current;
  const active = ["queued", "running"].includes(session.status);
  const chosen = session.iterations.find((r) => r.id === session.best_iteration_id);
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
  const acceptable =
    chosen?.verdict !== "inconclusive" &&
    chosen?.verdict_detail?.broken != null &&
    Number(chosen.verdict_detail.broken) === 0;
  const blockedChanges = selectedBatch?.hunks.some(
    (hunk) => hunk.status === "pending" && measuredIds.includes(hunk.id) && hunk.blocked !== null,
  );
  return (
    <div className="space-y-6">
      <nav data-tour="improvement-steps" aria-label={t("stepsLabel")}>
        <WizardSteps
          responsive
          steps={STEPS.map((id) => ({
            id,
            label: t(`steps.${id}`),
            status: states[id],
            statusLabel: t(`stepState.${states[id]}`),
            tourId: `improvement-step-${id}`,
          }))}
          current={step}
          onSelect={(id) => {
            const target = STEPS.find((item) => item === id);
            if (target) setSelected(target);
          }}
        />
      </nav>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4 text-sm">
        <p role="status" className="flex items-center gap-2 font-medium">
          {active ? (
            <Loader2 className="text-chart size-4 animate-spin" aria-hidden />
          ) : (
            <CircleDot className="text-muted-foreground size-4" aria-hidden />
          )}
          {t(`status.${session.status}`)}
        </p>
        <div className="w-full space-y-1.5 sm:w-64">
          <p className="text-muted-foreground">
            {t("spend", {
              spent: usd(session.spent_usd, locale),
              budget: usd(session.budget_usd, locale),
            })}
          </p>
          <div aria-hidden className="bg-muted h-1.5 overflow-hidden rounded-full">
            <div
              className="bg-chart h-full rounded-full"
              style={{
                width: `${Math.min(100, (Number(session.spent_usd) / Math.max(Number(session.budget_usd), 1e-9)) * 100)}%`,
              }}
            />
          </div>
        </div>
      </div>
      {session.stop_reason && (
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
      <div ref={content} className="space-y-6">
        {step === "understand" && <Understand session={session} />}
        {step === "testSet" && <TestQuestions session={session} />}
        {step === "today" && <Today session={session} />}
        {step === "changes" && (
          <section className="grid gap-6 md:grid-cols-[2fr_1fr]" data-tour="improvement-changes">
            {chosen && selectedBatch?.hunks.length ? (
              <ChangeSelection
                session={session}
                round={chosen}
                hunks={selectedBatch.hunks}
                included={included}
                onChange={(ids) => setDraftSelection({ roundId: chosen.id, ids })}
                onStarted={() => {
                  setDraftSelection(null);
                  setSelected(null);
                  setConfirm(false);
                }}
              />
            ) : active ? (
              <p className="rounded-xl border p-6 text-sm">{t("changesWorking")}</p>
            ) : (
              <section className="space-y-3 rounded-xl border p-6 text-sm">
                <p>{t("noChangesFound")}</p>
                <ul className="list-disc space-y-1 pl-5">
                  {session.iterations.map((round) => (
                    <li key={round.id}>
                      {t("triedAttempt", {
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
          <CheckProgress session={session} onShowResult={() => setSelected("result")} />
        )}
        {step === "result" && (
          <section className="space-y-4" data-tour="improvement-results">
            <ResultSummary session={session} round={chosen} />
            {session.iterations.map((round) =>
              round.id === session.best_iteration_id || !session.best_iteration_id ? (
                <RoundResults key={round.id} session={session} round={round} />
              ) : (
                <RoundHistory key={round.id} session={session} round={round} />
              ),
            )}
            <details className="rounded-xl border p-4">
              <summary className="cursor-pointer text-sm font-medium">
                {t("knowledgeCheckDetails")}
              </summary>
              <div className="mt-4">
                <KnowledgeDrafts session={session} />
              </div>
            </details>
          </section>
        )}
        {step === "accept" && (session.status === "published" || session.status === "accepted") && (
          <DoneScreen session={session} />
        )}
        {step === "accept" && session.status !== "published" && session.status !== "accepted" && (
          <section className="space-y-4 rounded-xl border p-6" data-tour="improvement-accept">
            <h2 className="font-medium">{t("steps.accept")}</h2>
            <AcceptSummary session={session} round={chosen} />
            {session.status === "ready" && <KnowledgeDocuments session={session} accept />}
            {session.status === "ready" && (
              <>
                {missingBatch &&
                  (authoringQuery.error ? (
                    <ErrorState
                      description={getErrorMessage(authoringQuery.error, tErrors)}
                      cta={{ label: t("retryRead"), onClick: () => void authoringQuery.refetch() }}
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
                    variant="outline"
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
        <StepDecisions session={session} step={step} />
      </div>
      {selectionDirty && (
        <p role="alert" className="text-sm">
          {t("selectionNeedsCheck")}
        </p>
      )}
      {(step === "result" || session.status === "failed" || session.stop_reason === "budget") && (
        <ContinueSession
          session={session}
          lead={
            step === "result" &&
            session.status === "ready" && (
              <Button
                variant={acceptable ? "default" : "outline"}
                disabled={selectionDirty || missingBatch}
                onClick={() => setSelected("accept")}
              >
                {t("accept")}
              </Button>
            )
          }
          onStarted={() => {
            setSelected(null);
            setDraftSelection(null);
            setConfirm(false);
          }}
        />
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        {STEPS.indexOf(step) > 0 ? (
          <Button variant="outline" onClick={() => setSelected(STEPS[STEPS.indexOf(step) - 1]!)}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
            {t("previousStep")}
          </Button>
        ) : (
          <span />
        )}
        {step !== "result" && step !== "accept" && (
          <Button variant="outline" onClick={() => setSelected(STEPS[STEPS.indexOf(step) + 1]!)}>
            {t("nextStep")}
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {active && (
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
  );
}
