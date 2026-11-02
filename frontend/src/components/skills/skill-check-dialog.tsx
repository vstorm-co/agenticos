"use client";

import { useEffect, useState } from "react";
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
import { useOpenSkillCheck, useSkillCheck } from "@/hooks/use-skill-check";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { CheckAgents } from "./check-agents";
import { CheckDecision } from "./check-decision";

/**
 * Check a waiting skill change on every agent of its line, then decide it.
 *
 * Opening it prices the check; nothing runs until Start. Each agent answers its
 * questions with the stored text and with the change, and the result per agent
 * decides what applying may do.
 */
export function SkillCheckDialog({
  skillId,
  proposalId,
  forkId,
  onOpenChange,
}: {
  skillId: string;
  proposalId: string;
  forkId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("skills.check");
  const tErrors = useTranslations("errors");
  const [started, setStarted] = useState<string | null>(null);
  const earlier = useOpenSkillCheck(skillId, forkId, proposalId);
  const checkId = started ?? earlier.data?.id ?? null;
  const { check, estimate, start, apply, discard, cancel } = useSkillCheck(skillId, checkId);
  const body = { fork_id: forkId, proposal_id: proposalId };
  const { mutate: price } = estimate;
  // Priced only when no earlier check of this change is still open to go back to.
  const fresh = earlier.isSuccess && earlier.data === null;
  useEffect(() => {
    if (fresh) price({ fork_id: forkId, proposal_id: proposalId });
  }, [fresh, price, forkId, proposalId]);
  const failed = (error: unknown) => toast.error(getErrorMessage(error, tErrors));
  const shown = check ?? estimate.data ?? null;

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
        {shown !== null && <CheckAgents agents={shown.agents} hidden={shown.hidden} />}
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
                start.mutate(body, { onSuccess: (made) => setStarted(made.id), onError: failed })
              }
            >
              {t("start")}
            </Button>
          </DialogFooter>
        )}
        {check?.status === "running" && (
          <DialogFooter className="items-center gap-3 sm:justify-between">
            <p className="text-muted-foreground text-sm">{t("running")}</p>
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
        {check?.status === "done" && (
          <CheckDecision
            check={check}
            busy={apply.isPending || discard.isPending}
            onApply={(decision) =>
              apply.mutate(decision, { onSuccess: () => onOpenChange(false), onError: failed })
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
