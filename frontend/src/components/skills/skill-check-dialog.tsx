"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Skeleton,
} from "@/components/ui";
import { AddTestQuestions } from "@/components/skill-improvement/add-test-questions";
import { SetUpGrading } from "@/components/skill-improvement/set-up-grading";
import { CheckAgents } from "@/components/skill-improvement/check-agents";
import { useSkillCheck, type SkillCheckBody } from "@/hooks/use-skill-check";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { formatCostUsd } from "@/lib/utils";
import type { SkillCheck, SkillCheckEstimate } from "@/types/skill-checks";
import { CheckDecision } from "./check-decision";
import { CheckPlan, CheckProgress } from "./check-plan";

/** A refusal naming the line's newer version: the text was written over an older one. */
function lineMoved(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.code === "CONCURRENT_CHANGE" &&
    error.details?.version !== undefined
  );
}

/** A checked text taken back to an editor, with the version and line it was written over. */
export interface CheckedDraft {
  description: string;
  content: string;
  baseVersionId: string;
  forkId: string | null;
}

/** Every agent of the line, the hidden ones too, is one nobody can check. */
function nobodyCheckable(plan: SkillCheckEstimate): boolean {
  return (
    plan.agents.length + plan.hidden > 0 &&
    plan.agents.every((row) => row.state === "unknown") &&
    plan.hidden_unknown === plan.hidden
  );
}

/**
 * Check a skill change on every agent of its line, then decide it: a waiting
 * change by its proposal, or a text the editor has not saved yet.
 *
 * Opening it prices the check; nothing runs until Start. Each agent answers its
 * questions with the stored text and with the change, and the result per agent
 * decides what applying may do. When no agent can be checked the dialog says so
 * before anything starts, and going on asks for that to be acknowledged. A check an
 * improvement session started is decided in that session, so the dialog points
 * there instead of deciding it. A check left running is opened again from the skill
 * page by its id, and is not priced again.
 */
export function SkillCheckDialog({
  skillId,
  change,
  resume,
  forkId,
  onOpenChange,
  onApplied,
  onLineMoved,
  onEdit,
  onChecked,
  canDecide = true,
}: {
  skillId: string;
  /**
   * What to check: a waiting proposal, or an unsaved text written over `baseVersionId`,
   * which the server refuses once the line has a newer version.
   */
  change?:
    | { proposalId: string }
    | { candidate: { description: string; content: string }; baseVersionId: string }
    | { updateAgentId: string };
  /** A check already started, opened again in place of a change to check. */
  resume?: string;
  forkId: string | null;
  onOpenChange: (open: boolean) => void;
  /** Called once the change went live from this check. */
  onApplied?: () => void;
  /** Called, in place of saying so here, when the line moved past the text's base. */
  onLineMoved?: () => void;
  /** Takes the checked text back to an editor; without it, improving further starts a session. */
  onEdit?: (draft: CheckedDraft) => void;
  /** An update check is decided by moving its agent, so its finished check goes back. */
  onChecked?: (check: SkillCheck) => void;
  /** Whether the reader may stop or decide the check, which needs edit access to the skill. */
  canDecide?: boolean;
}) {
  const t = useTranslations("skills.check");
  const tErrors = useTranslations("errors");
  const [checkId, setCheckId] = useState<string | null>(resume ?? null);
  const { check, reading, estimate, start, apply, fork, discard, cancel } = useSkillCheck(
    skillId,
    checkId,
  );
  const proposalId = change && "proposalId" in change ? change.proposalId : null;
  const description = change && "candidate" in change ? change.candidate.description : null;
  const content = change && "candidate" in change ? change.candidate.content : null;
  const baseVersionId = change && "candidate" in change ? change.baseVersionId : null;
  const updateAgentId = change && "updateAgentId" in change ? change.updateAgentId : null;
  const body = useMemo<SkillCheckBody>(
    () =>
      updateAgentId !== null
        ? { update_agent_id: updateAgentId }
        : proposalId !== null
          ? { fork_id: forkId, proposal_id: proposalId }
          : {
              fork_id: forkId,
              candidate: { description: description ?? "", content: content ?? "" },
              base_version_id: baseVersionId ?? undefined,
            },
    [forkId, proposalId, description, content, baseVersionId, updateAgentId],
  );
  const { mutate: price } = estimate;
  const pricing = change !== undefined;
  useEffect(() => {
    if (pricing) price(body);
  }, [pricing, price, body]);
  useEffect(() => {
    if (onLineMoved && lineMoved(estimate.error)) onLineMoved();
  }, [estimate.error, onLineMoved]);
  const [decidedIn, setDecidedIn] = useState<string | null>(null);
  const failed = (error: unknown) => {
    if (onLineMoved && lineMoved(error)) {
      onLineMoved();
      return;
    }
    const session =
      error instanceof ApiError && error.code === "DECIDE_IN_SESSION"
        ? error.details?.session_id
        : undefined;
    if (typeof session === "string") setDecidedIn(session);
    else toast.error(getErrorMessage(error, tErrors));
  };
  // The server knows whether this very text is checked already, and says which check.
  const resumeOrFail = (error: unknown) => {
    const open = error instanceof ApiError ? error.details?.check_id : undefined;
    if (typeof open === "string") setCheckId(open);
    else failed(error);
  };
  const plan = check === null ? (estimate.data ?? null) : null;
  const unchecked = plan !== null && nobodyCheckable(plan);
  const noReaders = plan !== null && plan.agents.length + plan.hidden === 0;
  const unknownFor = (...reasons: string[]) =>
    (plan?.agents ?? []).filter((row) => reasons.includes(row.unknown_reason ?? ""));
  const session = check?.session_id ?? decidedIn;

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        {estimate.isError && (
          <p className="text-destructive text-sm">{getErrorMessage(estimate.error, tErrors)}</p>
        )}
        {check === null && reading.error !== null && (
          <p role="alert" className="text-destructive text-sm">
            {getErrorMessage(reading.error, tErrors)}
          </p>
        )}
        {!pricing && reading.isLoading && <Skeleton className="h-24 w-full" />}
        {plan !== null && <CheckPlan agents={plan.agents} hidden={plan.hidden} />}
        {check?.status === "running" && <CheckProgress agents={check.agents} />}
        {check !== null && <CheckAgents check={check} />}
        {noReaders && <p className="text-sm">{t("noReaders")}</p>}
        {unchecked && (
          <div className="space-y-2">
            <p className="text-sm">{t("nobody")}</p>
            {unknownFor("no_questions", "all_evidence").length > 0 && (
              <AddTestQuestions skillId={skillId} onCreated={() => price(body)} />
            )}
            <SetUpGrading agents={unknownFor("unscorable")} />
          </div>
        )}
        {plan !== null && (
          <DialogFooter className="items-center gap-3 sm:justify-between">
            <p className="text-muted-foreground text-xs">
              {!plan.affordable
                ? t("unaffordable")
                : unchecked || noReaders
                  ? null
                  : t("price", {
                      expected: formatCostUsd(Number(plan.expected_usd)),
                      most: formatCostUsd(Number(plan.at_most_usd)),
                    })}
            </p>
            <Button
              variant={unchecked || noReaders ? "outline" : "default"}
              disabled={start.isPending || !plan.affordable}
              onClick={() =>
                start.mutate(body, {
                  onSuccess: (made) => setCheckId(made.id),
                  onError: resumeOrFail,
                })
              }
            >
              {unchecked || noReaders ? t("startUnchecked") : t("start")}
            </Button>
          </DialogFooter>
        )}
        {session !== null && (
          <DialogFooter className="items-center gap-3 sm:justify-between">
            <p className="text-muted-foreground text-sm">{t("inSession")}</p>
            <Button asChild>
              <Link href={`${ROUTES.SKILL_DETAIL(skillId)}/improve/${session}`}>
                {t("openSession")}
              </Link>
            </Button>
          </DialogFooter>
        )}
        {session === null && check?.status === "running" && (
          <DialogFooter className="items-center gap-3 sm:justify-between">
            <p className="text-muted-foreground text-sm">
              {t.rich("running", {
                page: (chunks) => (
                  <Link
                    className="underline underline-offset-4"
                    href={ROUTES.SKILL_DETAIL(skillId)}
                  >
                    {chunks}
                  </Link>
                ),
              })}
            </p>
            {canDecide && (
              <Button
                variant="ghost"
                disabled={cancel.isPending}
                onClick={() =>
                  cancel.mutate(undefined, {
                    onSuccess: () => onOpenChange(false),
                    onError: failed,
                  })
                }
              >
                {t("cancel")}
              </Button>
            )}
          </DialogFooter>
        )}
        {session === null && check?.status === "done" && onChecked && (
          <DialogFooter className="items-center gap-3 sm:justify-between">
            <p className="text-muted-foreground text-sm">{t("updateChecked")}</p>
            <Button onClick={() => onChecked(check)}>{t("backToChange")}</Button>
          </DialogFooter>
        )}
        {session === null &&
          check?.status === "done" &&
          !onChecked &&
          check.source === "catch_up" && (
            <DialogFooter>
              <p className="text-muted-foreground text-sm">{t("updateDecidedElsewhere")}</p>
            </DialogFooter>
          )}
        {session === null &&
          check?.status === "done" &&
          !onChecked &&
          check.source !== "catch_up" &&
          canDecide && (
            <CheckDecision
              check={check}
              busy={apply.isPending || fork.isPending || discard.isPending}
              onEdit={
                onEdit &&
                (() => {
                  onEdit({
                    ...check.candidate,
                    baseVersionId: check.base_version.id,
                    forkId: check.line.fork_id,
                  });
                  onOpenChange(false);
                })
              }
              onFork={(choice) =>
                fork.mutateAsync(choice).then(
                  () => {
                    onApplied?.();
                    onOpenChange(false);
                    return null;
                  },
                  (error: unknown) => getErrorMessage(error, tErrors),
                )
              }
              onApply={(decision) =>
                apply.mutate(decision, {
                  onSuccess: () => {
                    onApplied?.();
                    onOpenChange(false);
                  },
                  onError: failed,
                })
              }
              onDiscard={() =>
                discard.mutate(undefined, { onSuccess: () => onOpenChange(false), onError: failed })
              }
            />
          )}
      </DialogContent>
    </Dialog>
  );
}
