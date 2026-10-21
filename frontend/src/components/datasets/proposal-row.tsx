"use client";

import { Check, Pencil, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import type { CaseProposal } from "@/types/case-generation";

interface ProposalRowProps {
  proposal: CaseProposal;
  disabled: boolean;
  onAccept: () => void;
  onEdit: () => void;
  onDismiss: () => void;
}

/**
 * One drafted case: its question, what it was drafted from, and the decision.
 *
 * Edit opens the case in the editor and accepts what is saved there, so an
 * edited draft and an accepted one are one decision rather than two.
 */
export function ProposalRow({ proposal, disabled, onAccept, onEdit, onDismiss }: ProposalRowProps) {
  const t = useTranslations("datasets");
  return (
    <li className="flex flex-wrap items-start gap-3 border-b py-3 last:border-b-0">
      <div className="min-w-0 flex-1 space-y-1.5">
        <span className="text-foreground line-clamp-2 block text-sm">{proposal.input}</span>
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">{t(`origin.${proposal.origin}`)}</Badge>
          {proposal.reference_answer !== null && (
            <Badge variant="outline">{t("hasReference")}</Badge>
          )}
          {proposal.expected_tool_calls.length > 0 && (
            <Badge variant="outline">
              {t("expectedCalls", { count: proposal.expected_tool_calls.length })}
            </Badge>
          )}
          {proposal.tags.map((tag) => (
            <Badge key={tag} variant="outline" className="font-mono">
              {tag}
            </Badge>
          ))}
        </span>
        {proposal.note !== null && (
          <span className="text-muted-foreground block text-xs">{proposal.note}</span>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={onDismiss}
          aria-label={t("dismissProposal")}
        >
          <X className="h-4 w-4" aria-hidden />
          {t("dismiss")}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={onEdit}
          aria-label={t("editProposal")}
        >
          <Pencil className="h-4 w-4" aria-hidden />
          {t("edit")}
        </Button>
        <Button size="sm" disabled={disabled} onClick={onAccept} aria-label={t("acceptProposal")}>
          <Check className="h-4 w-4" aria-hidden />
          {t("accept")}
        </Button>
      </div>
    </li>
  );
}
