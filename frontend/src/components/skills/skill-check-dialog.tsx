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
} from "@/components/ui";
import { useSkillCheck } from "@/hooks/use-skill-check";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { CheckAgents } from "./check-agents";
import { CheckDecision } from "./check-decision";

/** A refusal naming the line's newer version: the text was written over an older one. */
function lineMoved(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.code === "CONCURRENT_CHANGE" &&
    error.details?.version !== undefined
  );
}

/**
 * Check a skill change on every agent of its line, then decide it: a waiting
 * change by its proposal, or a text the editor has not saved yet.
 *
 * Opening it prices the check; nothing runs until Start. Each agent answers its
 * questions with the stored text and with the change, and the result per agent
 * decides what applying may do. A check an improvement session started is decided
 * in that session, so the dialog points there instead of deciding it. A check left
 * running is opened again from the skill page by its id, and is not priced again.
 */
export function SkillCheckDialog({
  skillId,
  change,
  resume,
  forkId,
  onOpenChange,
  onApplied,
  onLineMoved,
}: {
  skillId: string;
  /**
   * What to check: a waiting proposal, or an unsaved text written over `baseVersionId`,
   * which the server refuses once the line has a newer version.
   */
  change?:
    | { proposalId: string }
    | { candidate: { description: string; content: string }; baseVersionId: string };
  /** A check already started, opened again in place of a change to check. */
  resume?: string;
  forkId: string | null;
  onOpenChange: (open: boolean) => void;
  /** Called once the change went live from this check. */
  onApplied?: () => void;
  /** Called, in place of saying so here, when the line moved past the text's base. */
  onLineMoved?: () => void;
}) {
  const t = useTranslations("skills.check");
  const tErrors = useTranslations("errors");
  const [checkId, setCheckId] = useState<string | null>(resume ?? null);
  const { check, estimate, start, apply, discard, cancel } = useSkillCheck(skillId, checkId);
  const proposalId = change && "proposalId" in change ? change.proposalId : null;
  const description = change && "candidate" in change ? change.candidate.description : null;
  const content = change && "candidate" in change ? change.candidate.content : null;
  const baseVersionId = change && "candidate" in change ? change.baseVersionId : null;
  const body = useMemo(
    () =>
      proposalId !== null
        ? { fork_id: forkId, proposal_id: proposalId }
        : {
            fork_id: forkId,
            candidate: { description: description ?? "", content: content ?? "" },
            base_version_id: baseVersionId ?? undefined,
          },
    [forkId, proposalId, description, content, baseVersionId],
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
  const shown = check ?? estimate.data ?? null;
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
        {shown !== null && (
          <CheckAgents
            agents={shown.agents}
            hidden={shown.hidden}
            running={check?.status === "running"}
          />
        )}
        {check === null && estimate.data && (
          <DialogFooter className="items-center gap-3 sm:justify-between">
            <p className="text-muted-foreground text-xs">
              {estimate.data.affordable
                ? t("price", {
                    expected: estimate.data.expected_usd,
                    most: estimate.data.at_most_usd,
                  })
                : t("unaffordable")}
            </p>
            <Button
              disabled={start.isPending || !estimate.data.affordable}
              onClick={() =>
                start.mutate(body, {
                  onSuccess: (made) => setCheckId(made.id),
                  onError: resumeOrFail,
                })
              }
            >
              {t("start")}
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
            <Button
              variant="ghost"
              disabled={cancel.isPending}
              onClick={() =>
                cancel.mutate(undefined, { onSuccess: () => onOpenChange(false), onError: failed })
              }
            >
              {t("cancel")}
            </Button>
          </DialogFooter>
        )}
        {session === null && check?.status === "done" && (
          <CheckDecision
            check={check}
            busy={apply.isPending || discard.isPending}
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
