"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import type { ProposalCreate, ProposalRead } from "@/lib/failure-learning-api";

import { ProposalForm } from "./proposal-form";
import { ProposalReview } from "./proposal-review";

/**
 * The agent's proposals: draft, applied and rejected, each reviewed in
 * place. Creating one needs the try that evidences it, so the form opens
 * pre-linked from a try or from an entry; a proposal written with no
 * evidence at all is a guess, and the review says so.
 */
export function ProposalsPanel({
  proposals,
  isLoading,
  error,
  ledgerEntryId,
  canEdit,
  canApplyInstructions,
  canApplySkill,
  canTry,
  canRevert,
  canReject,
  prefill,
  onCreate,
  onApply,
  onTry,
  onRevert,
  onReject,
  onPrefillConsumed,
}: {
  proposals: ProposalRead[];
  isLoading: boolean;
  error: Error | null;
  ledgerEntryId: string | null;
  canEdit: boolean;
  canApplyInstructions: boolean;
  canApplySkill: boolean;
  canTry: boolean;
  canRevert: boolean;
  canReject: boolean;
  /** A try whose passing text pre-fills the create form. */
  prefill: { evalTryId: string; newText: string } | null;
  onCreate: (input: ProposalCreate) => void;
  onApply: (proposalId: string) => void;
  onTry: (proposalId: string) => void;
  onRevert: (proposalId: string) => void;
  onReject: (proposalId: string, reason: string) => void;
  onPrefillConsumed: () => void;
}) {
  const t = useTranslations("failureLearning");
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const shown =
    ledgerEntryId === null
      ? proposals
      : proposals.filter((proposal) => proposal.ledger_entry_id === ledgerEntryId);
  const selected = shown.find((proposal) => proposal.id === selectedId) ?? null;
  const creatingWithPrefill = creating || prefill !== null;

  if (isLoading) return <LoadingState variant="skeleton-list" />;
  if (error) return <ErrorState />;
  return (
    <div className="space-y-3">
      {shown.length === 0 && !creatingWithPrefill && <EmptyState title={t("noProposals")} />}
      {shown.map((proposal) => (
        <Card key={proposal.id}>
          <CardContent className="flex flex-wrap items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <p className="line-clamp-2 break-words">{proposal.new_text}</p>
              <p className="text-muted-foreground text-sm">
                {t(proposal.target_type === "skill" ? "targetSkill" : "targetInstructions")}
              </p>
            </div>
            <Badge variant={proposal.status === "applied" ? "default" : "secondary"}>
              {t(
                proposal.status === "draft"
                  ? "statusDraft"
                  : proposal.status === "applied"
                    ? "statusApplied"
                    : "statusRejected",
              )}
            </Badge>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setSelectedId(selectedId === proposal.id ? null : proposal.id)}
            >
              {selectedId === proposal.id ? t("cancel") : t("review")}
            </Button>
          </CardContent>
        </Card>
      ))}
      {selected && (
        <ProposalReview
          proposal={selected}
          canApplyInstructions={canApplyInstructions}
          canApplySkill={canApplySkill}
          canTry={canTry}
          canRevert={canRevert}
          canReject={canReject}
          onApply={() => onApply(selected.id)}
          onTry={() => onTry(selected.id)}
          onRevert={() => onRevert(selected.id)}
          onReject={(reason) => onReject(selected.id, reason)}
        />
      )}
      {canEdit && !creatingWithPrefill && (
        <Button type="button" variant="outline" onClick={() => setCreating(true)}>
          {t("newProposal")}
        </Button>
      )}
      {creatingWithPrefill && (
        <ProposalForm
          ledgerEntryId={ledgerEntryId}
          evalTryId={prefill?.evalTryId ?? null}
          initialNewText={prefill?.newText ?? ""}
          onSubmit={(input) => {
            onCreate(input);
            setCreating(false);
            onPrefillConsumed();
          }}
          onCancel={() => {
            setCreating(false);
            onPrefillConsumed();
          }}
        />
      )}
    </div>
  );
}
