"use client";
import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { WizardNav, WizardSteps } from "@/components/ui/wizard-steps";
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
  if (!agent.can_edit || !can(Perm.runsView)) return <p role="alert">{t("permission")}</p>;
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
        <p role="status">{t(`status.${session.status}`)}</p>
        <p>
          {t("spend", {
            spent: usd(session.spent_usd, locale),
            budget: usd(session.budget_usd, locale),
          })}
        </p>
      </div>
      {session.error && (
        <p role="alert" className="text-destructive text-sm">
          {session.error}
        </p>
      )}
      {session.stop_reason && <p className="text-sm">{t(`stop.${session.stop_reason}`)}</p>}
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
          <KnowledgeDocuments agentId={agentId} />
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
          {session.status === "ready" && <KnowledgeDocuments agentId={agentId} accept />}
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
                <GuardNote agentId={agentId} version={session.next_version} />
              )}
              <p className="text-muted-foreground text-sm" data-tour="improvement-guard">
                {t("publishImpact")}
              </p>
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
      {selectionDirty && (
        <p role="alert" className="text-sm">
          {t("selectionNeedsCheck")}
        </p>
      )}
      {(step === "result" || session.status === "failed" || session.stop_reason === "budget") && (
        <ContinueSession
          session={session}
          onStarted={() => {
            setSelected(null);
            setDraftSelection(null);
            setConfirm(false);
          }}
        />
      )}
      <WizardNav
        backLabel={t("previousStep")}
        backIsStep={STEPS.indexOf(step) > 0}
        onBack={() => setSelected(STEPS[Math.max(0, STEPS.indexOf(step) - 1)]!)}
        nextLabel={t("nextStep")}
        nextDisabled={step === "accept"}
        onNext={() => setSelected(STEPS[Math.min(STEPS.length - 1, STEPS.indexOf(step) + 1)]!)}
      />
      <div className="flex flex-wrap items-center gap-3 border-t pt-4">
        {session.status === "ready" && (
          <Button
            variant={
              chosen?.verdict !== "inconclusive" &&
              chosen?.verdict_detail?.broken != null &&
              Number(chosen.verdict_detail.broken) === 0
                ? "default"
                : "outline"
            }
            disabled={selectionDirty || missingBatch}
            onClick={() => setSelected("accept")}
          >
            {t("accept")}
          </Button>
        )}
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
        <Link className="text-sm underline" href={`/agents/${agentId}/improve/new`}>
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
