"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { AttemptChanges } from "@/components/improvement/attempt-changes";
import { AttemptHistory } from "@/components/improvement/attempt-history";
import { ContinueSession } from "@/components/improvement/continue-session";
import { ImprovementShell, WorkingNote } from "@/components/improvement/improvement-shell";
import { type ReadOnlyReason } from "@/components/improvement/read-only";
import { TriedChanges } from "@/components/improvement/tried-changes";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { useSkill } from "@/hooks";
import { useImprovement } from "@/hooks/use-improvements";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useSkillMerge } from "@/hooks/use-skill-merge";
import {
  isActive,
  isClosed,
  isMerge,
  isReachable,
  standing,
  stopOf,
} from "@/lib/improvement-steps";
import { Perm } from "@/types/permissions";
import type { SkillImprovement } from "@/types/skill-improvement";
import type { MergeKind } from "@/types/skill-merge";
import { CheckAgain } from "./check-again";
import { CheckAgents } from "./check-agents";
import { CheckEstimate } from "./check-estimate";
import { MainAloneChoice, MainAloneResult } from "./main-alone";
import { MergeAgain } from "./merge-again";
import { MergeChanges } from "./merge-changes";
import { MergeStart } from "./merge-start";
import { SkillAccept } from "./skill-accept";
import { SkillStart } from "./skill-start";
import { SkillUnderstand } from "./skill-understand";

/**
 * Improving a skill, step by step, on the line the person chose: the agent Improve
 * wizard's frame, with every step's result told agent by agent.
 */
export function SkillImprovementPage({
  skillId,
  sessionId,
  forkId,
  fromRun = null,
  merge = null,
}: {
  skillId: string;
  sessionId: string;
  /** For a new session, the line to improve; null is main. */
  forkId: string | null;
  /** For a new session, the agent session that handed its skill problems over. */
  fromRun?: string | null;
  /** For a new session on a fork, merging it with main instead of improving it. */
  merge?: MergeKind | null;
}) {
  const t = useTranslations("skillImprovement");
  const tErrors = useTranslations("errors");
  const { skill, isLoading, error } = useSkill(skillId);
  const { can } = usePermissions();
  if (isLoading) return <LoadingState variant="skeleton-cards" rows={3} />;
  if (error || !skill) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  const header = (
    <PageHeader
      title={t("title", { name: skill.name })}
      breadcrumbs={[
        { label: t("skills"), href: ROUTES.SKILLS },
        { label: skill.name, href: ROUTES.SKILL_DETAIL(skillId) },
        { label: t("heading") },
      ]}
    />
  );
  // A session is read from the line agents' runs; starting one changes the skill too.
  if (!can(Perm.runsView) || (!skill.can_edit && sessionId === "new"))
    return (
      <div className="mx-auto w-full max-w-5xl space-y-6 pb-16">
        {header}
        <p role="alert">{t("permission")}</p>
        <Link className="text-sm underline underline-offset-4" href={ROUTES.SKILL_DETAIL(skillId)}>
          {t("openSkill")}
        </Link>
      </div>
    );
  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 pb-16">
      {header}
      {sessionId === "new" && merge !== null && forkId !== null ? (
        <MergeStart skillId={skillId} forkId={forkId} kind={merge} />
      ) : sessionId === "new" ? (
        <SkillStart skillId={skillId} forkId={forkId} fromRun={fromRun} />
      ) : (
        <SkillSession skillId={skillId} sessionId={sessionId} canEdit={skill.can_edit === true} />
      )}
    </div>
  );
}

function SkillSession({
  skillId,
  sessionId,
  canEdit,
}: {
  skillId: string;
  sessionId: string;
  canEdit: boolean;
}) {
  const t = useTranslations("skillImprovement");
  const tImprovement = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const actions = useImprovement({ skillId }, sessionId);
  const [wordingOpen, setWordingOpen] = useState(false);
  const [mainAlone, setMainAlone] = useState(true);
  const session = actions.session as SkillImprovement | undefined;
  const merging = session !== undefined && isMerge(session);
  // Read once the session stops at Changes; while it works, the model is still writing.
  const { merge } = useSkillMerge(skillId, sessionId, {
    at: session ? standing(session) : "",
    enabled: merging && !isActive(session),
  });
  const catchUp = session?.purpose === "catch_up";
  const body = useMemo(
    () => (catchUp ? { main_alone: mainAlone } : undefined),
    [catchUp, mainAlone],
  );
  if (actions.isLoading) return <LoadingState variant="skeleton-cards" rows={3} />;
  if (actions.error || !session)
    return (
      <ErrorState
        description={getErrorMessage(actions.error, tErrors)}
        cta={{ label: tImprovement("retryRead"), onClick: () => void actions.refetch() }}
      />
    );
  const readOnly: ReadOnlyReason | null = isClosed(session)
    ? "finished"
    : canEdit
      ? null
      : "viewOnly";
  const check = session.check;
  const measured = check ? (
    <CheckAgents check={check} />
  ) : (
    <WorkingNote>{t("checkWaiting")}</WorkingNote>
  );
  return (
    <ImprovementShell
      session={session}
      readOnly={readOnly}
      closeHref={ROUTES.SKILL_DETAIL(skillId)}
      wordingOpen={wordingOpen}
      nextStepDetail={(quote) => (
        <>
          <CheckEstimate quote={quote} />
          {catchUp && <MainAloneChoice quote={quote} checked={mainAlone} onChange={setMainAlone} />}
        </>
      )}
      nextStep={
        merging
          ? {
              hint: t(`mergeHint.${session.purpose}`),
              blocked: !merge
                ? t("mergeReading")
                : merge.unresolved
                  ? t("settleFirst", { count: merge.unresolved })
                  : undefined,
              body,
              revision: merge?.updated_at ?? null,
            }
          : undefined
      }
      panel={({ step, views, goTo, followCurrent }) => (
        <>
          <p className="text-muted-foreground text-sm">{t("line", { line: session.line_name })}</p>
          {step === "understand" &&
            (views.understand.content === "working" ? (
              <WorkingNote>{tImprovement("understandWorking")}</WorkingNote>
            ) : (
              <SkillUnderstand session={session} />
            ))}
          {step === "changes" && merging ? (
            isActive(session) && views.changes.content === "working" ? (
              <WorkingNote>{t("mergeWorking")}</WorkingNote>
            ) : (
              <MergeChanges
                session={session}
                editable={readOnly === null && stopOf(session) === "changes"}
              />
            )
          ) : (
            step === "changes" &&
            (stopOf(session) === "changes" ? (
              <section className="space-y-4">
                {session.stale && (
                  <p role="status" className="text-warning text-sm">
                    {t("staleChanges")}
                  </p>
                )}
                <AttemptHistory session={session} />
                <h2 className="font-medium">
                  {tImprovement("round", {
                    number: session.iteration,
                    max: session.max_iterations,
                  })}
                </h2>
                <AttemptChanges
                  session={session}
                  editable={readOnly === null}
                  onEditing={setWordingOpen}
                />
              </section>
            ) : isActive(session) && views.changes.content === "working" ? (
              <WorkingNote>{tImprovement("changesWorking")}</WorkingNote>
            ) : (
              <TriedChanges session={session} />
            ))
          )}
          {step === "check" && (
            <section className="space-y-4 rounded-xl border p-6">
              <h2 className="font-medium">{t("checkTitle")}</h2>
              {measured}
              <MainAloneResult session={session} />
            </section>
          )}
          {step === "result" && (
            <section className="space-y-4 rounded-xl border p-6">
              <h2 className="font-medium">{t("resultTitle")}</h2>
              {measured}
              <MainAloneResult session={session} />
              {session.stale &&
                readOnly === null &&
                (merging ? (
                  <MergeAgain session={session} />
                ) : (
                  <CheckAgain session={session} onStarted={followCurrent} />
                ))}
              {isReachable(views.accept) ? (
                <Button onClick={() => goTo("accept")}>{t("toAccept")}</Button>
              ) : (
                readOnly === null && (
                  <ContinueSession
                    session={session}
                    emphasis={{ again: "default", end: "outline" }}
                    onStarted={followCurrent}
                  />
                )
              )}
            </section>
          )}
          {step === "accept" &&
            (check && !isClosed(session) ? (
              <SkillAccept session={session} check={check} onStarted={followCurrent} />
            ) : (
              <p className="text-sm">{t("acceptClosed")}</p>
            ))}
        </>
      )}
    />
  );
}
