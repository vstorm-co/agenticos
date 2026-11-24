"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Badge, Button, Card, CardContent, Input, Label, LineDiff } from "@/components/ui";
import type { ProposalRead } from "@/lib/failure-learning-api";

import { TryView } from "./try-view";

/**
 * One proposal, read as the approver will read it: the change itself, the
 * eval evidence that backs it, and what applying it will do. Instruction and
 * skill targets are gated alike: applying needs a try that passed the gate
 * for this exact text. A try of a skill proposal runs its new content, so
 * the review can start one. An applied skill can be reverted once, while
 * the skill still holds the content the apply wrote.
 */
export function ProposalReview({
  proposal,
  canApplyInstructions,
  canApplySkill,
  canTry,
  canRevert,
  canReject,
  onApply,
  onTry,
  onRevert,
  onReject,
}: {
  proposal: ProposalRead;
  canApplyInstructions: boolean;
  canApplySkill: boolean;
  canTry: boolean;
  canRevert: boolean;
  canReject: boolean;
  onApply: () => void;
  onTry: () => void;
  onRevert: () => void;
  onReject: (reason: string) => void;
}) {
  const t = useTranslations("failureLearning");
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  // The evidence is embedded in the proposal: the try as it stood when the
  // proposal was read, so the review needs no second fetch.
  const evidence = proposal.eval_evidence;
  const isSkill = proposal.target_type === "skill";
  const canApply = isSkill ? canApplySkill : canApplyInstructions;
  const gatePassed = evidence?.gate_passed === true;

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={proposal.status === "applied" ? "default" : "secondary"}>
            {t(
              proposal.status === "draft"
                ? "statusDraft"
                : proposal.status === "applied"
                  ? "statusApplied"
                  : "statusRejected",
            )}
          </Badge>
          <span className="text-muted-foreground text-sm">
            {t(isSkill ? "targetSkill" : "targetInstructions")}
          </span>
          {proposal.applied_version !== null && (
            <span className="text-muted-foreground text-sm">
              {t("appliedVersion", { number: proposal.applied_version.number })}
            </span>
          )}
        </div>
        <LineDiff
          before={proposal.old_text}
          after={proposal.new_text}
          identicalLabel={t("diffIdentical")}
          unchangedLabel={(count) => t("diffUnchanged", { count })}
          tooLongLabel={t("diffTooLong")}
        />
        <p className="text-sm whitespace-pre-wrap">{proposal.rationale}</p>
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("evalEvidence")}</p>
          {evidence === null && (
            <p className="text-muted-foreground text-sm">{t("noEvalEvidence")}</p>
          )}
          {evidence !== null && <TryView evaluation={evidence} />}
        </div>
        {proposal.status === "draft" && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              {canApply && (
                <Button
                  type="button"
                  disabled={!gatePassed}
                  title={gatePassed ? undefined : t("gateFailed")}
                  onClick={onApply}
                >
                  {t("apply")}
                </Button>
              )}
              {canTry && (
                <Button type="button" variant="outline" onClick={onTry}>
                  {t("tryThisText")}
                </Button>
              )}
              {canReject && !rejecting && (
                <Button type="button" variant="outline" onClick={() => setRejecting(true)}>
                  {t("reject")}
                </Button>
              )}
              {canReject && rejecting && (
                <>
                  <div className="min-w-64 flex-1 space-y-1.5">
                    <Label htmlFor="reject-reason">{t("rejectReasonLabel")}</Label>
                    <Input
                      id="reject-reason"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder={t("rejectReasonPlaceholder")}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={reason.trim() === ""}
                    onClick={() => onReject(reason.trim())}
                  >
                    {t("reject")}
                  </Button>
                </>
              )}
            </div>
            {canTry && <p className="text-muted-foreground text-sm">{t("tryThisTextHint")}</p>}
          </div>
        )}
        {proposal.status === "applied" && proposal.rollback_available && canRevert && (
          <div className="space-y-2">
            <Button type="button" variant="outline" onClick={onRevert}>
              {t("revert")}
            </Button>
            <p className="text-muted-foreground text-sm">{t("revertHint")}</p>
          </div>
        )}
        {proposal.status === "applied" && proposal.reverted_at !== null && (
          <p className="text-muted-foreground text-sm">{t("reverted")}</p>
        )}
      </CardContent>
    </Card>
  );
}
