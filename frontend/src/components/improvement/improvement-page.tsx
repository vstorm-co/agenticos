"use client";
import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, Checkbox } from "@/components/ui";
import { ChangeSelection } from "./change-selection";
import { useAgent } from "@/hooks/use-agents";
import { useAgentAuthoring } from "@/hooks/use-authoring";
import { useImprovement } from "@/hooks/use-improvements";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { useOrgStore } from "@/stores/org-store";
import { Perm } from "@/types/permissions";
import { ImprovementStartRedirect } from "./improvement-start-redirect";
import { KnowledgeDrafts } from "./knowledge-drafts";
import { SkillHandoffs } from "./skill-handoffs";
import { TestQuestions } from "./session-inputs";
import { Understand } from "./understand";
import { AttemptChanges } from "./attempt-changes";
import { AttemptHistory } from "./attempt-history";
import { CheckProgress } from "./check-progress";
import { AcceptedChanges, TriedChanges } from "./tried-changes";
import { NotBetterWarning } from "./attempt-choice";
import { AcceptSummary, GuardNote, KnowledgeDocuments } from "./outcome";
import { ResultStep } from "./result-decision";
import { type ReadOnlyReason } from "./read-only";
import { SessionDecision } from "./session-decision";
import { ImprovementShell, WorkingNote } from "./improvement-shell";
import { hasCandidate, isActive, isClosed, stopOf } from "@/lib/improvement-steps";

export function ImprovementPage({ agentId, sessionId }: { agentId: string; sessionId: string }) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { agent, isLoading, error } = useAgent(agentId);
  const { can } = usePermissions();
  if (isLoading) return <LoadingState variant="pending" />;
  if (error || !agent) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  // Reading a session needs the agent and its runs; starting one, or changing
  // one, needs edit access too, and without it the session is only read.
  if (!can(Perm.runsView) || (!agent.can_edit && sessionId === "new"))
    return (
      <div className="mx-auto w-full max-w-screen-2xl min-w-0 space-y-4 pb-8 sm:space-y-6 sm:pb-12">
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
  if (sessionId === "new") return <ImprovementStartRedirect agentId={agentId} />;
  return (
    <div className="mx-auto w-full max-w-screen-2xl min-w-0 space-y-4 pb-8 sm:space-y-6 sm:pb-12">
      <PageHeader
        title={t("title", { name: agent.name })}
        breadcrumbs={[{ label: agent.name, href: `/agents/${agentId}` }, { label: t("heading") }]}
      />
      <Session
        key={`${orgId}:${agentId}:${sessionId}`}
        agentId={agentId}
        sessionId={sessionId}
        agentName={agent.name}
        canPublish={agent.can_publish === true}
        canEdit={agent.can_edit === true}
      />
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
  const [automaticChoice, setAutomatic] = useState<boolean | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [draftSelection, setDraftSelection] = useState<{ roundId: string; ids: string[] } | null>(
    null,
  );
  const [wordingOpen, setWordingOpen] = useState(false);
  const session = actions.session;
  if (actions.isLoading) return <LoadingState variant="pending" />;
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
  const active = isActive(session);
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
  const blockedChanges = selectedBatch?.hunks.some(
    (hunk) => hunk.status === "pending" && measuredIds.includes(hunk.id) && hunk.blocked !== null,
  );
  const knowledgeCheck = <KnowledgeDrafts session={session} />;
  return (
    <ImprovementShell
      session={session}
      readOnly={readOnly}
      closeHref={`/agents/${agentId}`}
      wordingOpen={wordingOpen}
      footer={
        selectionDirty &&
        readOnly === null && (
          <p role="alert" className="text-sm">
            {t("selectionNeedsCheck")}
          </p>
        )
      }
      onRestart={() => {
        setDraftSelection(null);
        setConfirm(false);
      }}
      panel={({ step, views, goTo, followCurrent, act }) => (
        <>
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
                  <SkillHandoffs session={session} />
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
                    <p role="alert" className="text-warning-ink text-sm">
                      {t("blockedChanges")}
                    </p>
                  )}
                  {session.offer_automatic_check && (
                    <label
                      className="flex items-start gap-2 text-sm"
                      data-tour="improvement-automatic-check"
                    >
                      <Checkbox
                        className="mt-0.5"
                        checked={automatic}
                        onCheckedChange={(checked) => setAutomatic(checked === true)}
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
                    <Checkbox
                      className="mt-0.5"
                      checked={confirm}
                      onCheckedChange={(checked) => setConfirm(checked === true)}
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
        </>
      )}
    />
  );
}
