"use client";

import { useState } from "react";
import { Check, Sparkles, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { Button, ListCard, PAGE_SIZE, Pager } from "@/components/ui";
import { useCaseGenerations, useCaseProposals } from "@/hooks/use-case-generation";
import { getErrorMessage } from "@/lib/api-error";
import type { CaseProposal } from "@/types/case-generation";
import { CaseEditorDialog } from "./case-editor-dialog";
import { draftOf } from "./case-form";
import { GenerationStatus } from "./generation-status";
import { ProposalRow } from "./proposal-row";

interface ProposedCasesProps {
  datasetId: string;
  /** Whether the reader may decide. Without it the routes answer 404, so nothing is asked. */
  canEdit: boolean;
}

/**
 * Drafted cases waiting outside the dataset for a person's decision.
 *
 * Absent when nothing waits and nothing is being drafted, which is the normal
 * state. Drafts from chats are counted, not shown, to a reader who may not view
 * runs. "Accept all" and "Dismiss all" act on the page on screen: a decision is
 * made about cases somebody could read, never about ones beyond the pager.
 */
export function ProposedCases({ datasetId, canEdit }: ProposedCasesProps) {
  const t = useTranslations("datasets");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<CaseProposal | null>(null);
  const { generations } = useCaseGenerations(datasetId, { enabled: canEdit });
  const proposals = useCaseProposals(datasetId, {
    enabled: canEdit,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const latest = generations[0];

  if (!canEdit) return null;
  if (
    proposals.total === 0 &&
    proposals.hidden === 0 &&
    (latest === undefined || latest.status === "ready")
  )
    return null;

  const onPage = proposals.proposals.map((proposal) => proposal.id);
  const pageCount = Math.max(1, Math.ceil(proposals.total / PAGE_SIZE));
  return (
    <ListCard
      title={t("proposedCases")}
      counted={t("proposalCount", { count: proposals.total })}
      controls={
        onPage.length > 0 && (
          <div className="flex items-center gap-1" data-tour="datasets-proposals">
            <Button
              variant="ghost"
              size="sm"
              disabled={proposals.isDeciding}
              onClick={() => proposals.dismiss.mutate(onPage)}
            >
              <X className="h-4 w-4" aria-hidden />
              {t("dismissAll")}
            </Button>
            <Button
              size="sm"
              disabled={proposals.isDeciding}
              onClick={() => proposals.accept.mutate(onPage.map((id) => ({ id })))}
            >
              <Check className="h-4 w-4" aria-hidden />
              {t("acceptAll")}
            </Button>
          </div>
        )
      }
    >
      <div className="space-y-4">
        <GenerationStatus generation={latest} />
        {proposals.hidden > 0 && (
          <p role="status" className="text-muted-foreground text-sm">
            {t("proposalsHidden", { count: proposals.hidden })}
          </p>
        )}
        {proposals.error ? (
          <ErrorState
            description={getErrorMessage(proposals.error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void proposals.refetch() }}
          />
        ) : proposals.total > 0 ? (
          <>
            <p className="text-muted-foreground flex items-center gap-2 text-xs">
              <Sparkles className="h-3.5 w-3.5" aria-hidden />
              {t("proposalsBody")}
            </p>
            <ul>
              {proposals.proposals.map((proposal) => (
                <ProposalRow
                  key={proposal.id}
                  proposal={proposal}
                  disabled={proposals.isDeciding}
                  onAccept={() => proposals.accept.mutate([{ id: proposal.id }])}
                  onEdit={() => setEditing(proposal)}
                  onDismiss={() => proposals.dismiss.mutate([proposal.id])}
                />
              ))}
            </ul>
            {pageCount > 1 && (
              <Pager
                page={page}
                pageCount={pageCount}
                matched={proposals.total}
                total={proposals.total}
                onPage={setPage}
                counted={t("proposalCount", { count: proposals.total })}
              />
            )}
          </>
        ) : null}
      </div>
      {editing !== null && (
        <CaseEditorDialog
          key={editing.id}
          open
          // Mounted open, so the only change it reports is closing.
          onOpenChange={() => setEditing(null)}
          initial={draftOf(editing)}
          title={t("editProposal")}
          description={t("editProposalBody")}
          saveLabel={t("accept")}
          onSave={(content) => proposals.accept.mutateAsync([{ id: editing.id, content }])}
        />
      )}
    </ListCard>
  );
}
