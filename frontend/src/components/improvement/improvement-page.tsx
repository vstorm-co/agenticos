"use client";
import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { WizardNav, WizardSteps } from "@/components/ui/wizard-steps";
import { usd } from "@/components/evals/format";
import { ChangePreview } from "@/components/authoring/result-dialog";
import { useAgent } from "@/hooks/use-agents";
import { useAgentAuthoring } from "@/hooks/use-authoring";
import { useImprovement } from "@/hooks/use-improvements";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { useOrgStore } from "@/stores/org-store";
import { Perm } from "@/types/permissions";
import type { Improvement } from "@/types/improvement";
import { StartSession } from "./start-session";
import { RoundResults } from "./round-results";

const STEPS = ["understand", "testSet", "today", "changes", "check", "result", "accept"] as const;
type Step = (typeof STEPS)[number];
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
function currentStep(session: Improvement): Step {
  if (session.status === "accepted" || session.status === "published") return "accept";
  if (session.status !== "queued" && session.status !== "running") return "result";
  if (session.stage === "evaluating" || session.stage === "judging") return "check";
  if (
    session.stage === "proposing" ||
    session.stage === "filtering" ||
    session.stage === "drafting"
  )
    return "changes";
  return "understand";
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
  const { authoring } = useAgentAuthoring(agentId);
  const [selected, setSelected] = useState<Step | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [automatic, setAutomatic] = useState(true);
  const [confirm, setConfirm] = useState(false);
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
  const current = currentStep(session);
  const step = selected ?? current;
  const active = ["queued", "running"].includes(session.status);
  const chosen = session.iterations.find((r) => r.id === session.best_iteration_id);
  const selectedBatch = authoring?.batch?.id === chosen?.batch_id ? authoring?.batch : null;
  return (
    <div className="space-y-6">
      <div data-tour="improvement-steps">
        <div className="sm:hidden">
          <WizardSteps
            compact
            steps={STEPS.map((id) => ({ id, label: t(`steps.${id}`) }))}
            current={current}
          />
        </div>
        <div className="hidden sm:block">
          <WizardSteps
            steps={STEPS.map((id) => ({ id, label: t(`steps.${id}`) }))}
            current={current}
          />
        </div>
        <details className="mt-4">
          <summary className="text-muted-foreground cursor-pointer text-sm">
            {t("stepsLabel")}
          </summary>
          <nav aria-label={t("stepsLabel")} className="mt-4 flex flex-wrap gap-2">
            {STEPS.map((id, index) => (
              <Button
                key={id}
                variant={step === id ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setSelected(id)}
              >
                {t("stepStatus", {
                  step: t(`steps.${id}`),
                  status: t(
                    id === current
                      ? active
                        ? "running"
                        : "needsYou"
                      : index < STEPS.indexOf(current)
                        ? "done"
                        : "waiting",
                  ),
                })}
              </Button>
            ))}
          </nav>
        </details>
      </div>
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
      {(step === "understand" || step === "testSet" || step === "today") && (
        <section className="space-y-3 rounded-xl border p-6">
          <h2 className="font-medium">{t(`steps.${step}`)}</h2>
          <p className="text-muted-foreground text-sm">{t(`explain.${step}`)}</p>
          <Link className="text-sm underline" href={`/datasets/${session.dataset_id}`}>
            {t("reviewQuestions")}
          </Link>
          {session.iterations
            .flatMap((r) => r.eval_run_ids)
            .map((id) => (
              <Link
                key={id}
                className="block text-sm underline"
                href={`/agents/${agentId}/evals/${id}`}
              >
                {t("openCheck")}
              </Link>
            ))}
        </section>
      )}
      {step === "changes" && (
        <section className="space-y-4" data-tour="improvement-changes">
          {selectedBatch?.hunks.length ? (
            selectedBatch.hunks.map((h) => <ChangePreview key={h.id} hunk={h} />)
          ) : (
            <p className="rounded-xl border p-6 text-sm">
              {t(active ? "changesWorking" : "noChanges")}
            </p>
          )}
        </section>
      )}
      {(step === "check" || step === "result") && (
        <section className="space-y-4" data-tour="improvement-results">
          {active && <p role="status">{t("background")}</p>}
          {session.iterations.map((round) => (
            <RoundResults key={round.id} session={session} round={round} />
          ))}
        </section>
      )}
      {step === "accept" && (
        <section className="space-y-4 rounded-xl border p-6" data-tour="improvement-accept">
          <h2 className="font-medium">{t("steps.accept")}</h2>
          <p className="text-sm">{t("acceptBody")}</p>
          {session.status === "ready" && (
            <>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={automatic}
                  onChange={(e) => setAutomatic(e.target.checked)}
                />
                {t("automatic")}
              </label>
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
                  disabled={!confirm || actions.finish.isPending}
                  onClick={() =>
                    void act(async () => {
                      await actions.finish.mutateAsync({
                        confirmed: true,
                        publish: false,
                        automatic_check: automatic,
                      });
                    })
                  }
                >
                  {t("keepDraft")}
                </Button>
                {canPublish && (
                  <Button
                    disabled={!confirm || actions.finish.isPending}
                    onClick={() =>
                      void act(async () => {
                        await actions.finish.mutateAsync({
                          confirmed: true,
                          publish: true,
                          automatic_check: automatic,
                        });
                      })
                    }
                  >
                    {t("publish")}
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
            variant={Number(chosen?.verdict_detail?.broken ?? 0) > 0 ? "outline" : "default"}
            onClick={() => setSelected("accept")}
          >
            {t("accept")}
          </Button>
        )}
        {session.status === "failed" &&
          ["proposing", "evaluating"].includes(session.stage ?? "") && (
            <Button
              disabled={actions.retry.isPending}
              onClick={() =>
                void act(async () => {
                  await actions.retry.mutateAsync();
                  setSelected(null);
                })
              }
            >
              {t("retryStep")}
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
