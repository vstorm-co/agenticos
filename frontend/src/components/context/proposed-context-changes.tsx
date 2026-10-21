"use client";

import { useState } from "react";
import { Check, ChevronDown, GitPullRequest, X } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { EvidenceList } from "@/components/authoring/evidence-list";
import { ContextCheckButton } from "@/components/authoring/skill-check-button";
import { TextDiff } from "@/components/authoring/text-diff";
import { useContextChanges } from "@/hooks/use-context-changes";
import type { ContextChange } from "@/types/authoring";

/**
 * Context file changes the authoring assistant proposed, waiting for a person.
 *
 * Absent when nothing waits, like the skills' panel. Applying is live for every
 * agent bound to the file, so each row names those agents and offers a check
 * with evals first; a file edited since the proposal can only be discarded.
 */
export function ProposedContextChanges({ canEdit }: { canEdit: boolean }) {
  const t = useTranslations("authoring.contextChanges");
  const { changes, error, apply, discard, isDeciding } = useContextChanges("pending");

  if (!canEdit) return null;
  if (error !== null) return <p className="text-destructive text-sm">{error}</p>;
  if (changes.length === 0) return null;

  return (
    <Card>
      <CardHeader className="space-y-1 border-b px-5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <GitPullRequest className="h-4 w-4" aria-hidden />
          {t("title")}
        </CardTitle>
        <CardDescription className="text-xs">
          {t("waiting", { count: changes.length })}
        </CardDescription>
      </CardHeader>
      <CardContent className="divide-border divide-y p-0">
        {changes.map((change) => (
          <ChangeRow
            key={change.id}
            change={change}
            disabled={isDeciding}
            onApply={() => apply(change.id)}
            onDiscard={() => discard(change.id)}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function ChangeRow({
  change,
  disabled,
  onApply,
  onDiscard,
}: {
  change: ContextChange;
  disabled: boolean;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const t = useTranslations("authoring.contextChanges");
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-3 px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm">{change.context_name}</span>
            {change.stale && <Badge variant="warning">{t("stale")}</Badge>}
          </div>
          <p className="text-muted-foreground text-xs">
            {change.used_by.length === 0
              ? t("usedByNobody")
              : t("usedBy", { agents: change.used_by.map((agent) => agent.name).join(", ") })}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <ContextCheckButton contextId={change.context_id} proposalId={change.id} />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-label={t("show", { name: change.context_name })}
          >
            <ChevronDown className="h-4 w-4" aria-hidden />
            {open ? t("hide") : t("review")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={disabled}
            onClick={onDiscard}
            aria-label={t("discardTo", { name: change.context_name })}
          >
            <X className="h-4 w-4" aria-hidden />
            {t("discard")}
          </Button>
          <Button
            size="sm"
            disabled={disabled || change.stale}
            title={t("liveHint")}
            onClick={onApply}
            aria-label={t("applyTo", { name: change.context_name })}
          >
            <Check className="h-4 w-4" aria-hidden />
            {t("apply")}
          </Button>
        </div>
      </div>
      {open && (
        <div className="space-y-3">
          {change.stale && (
            <p className="text-sm text-amber-700 dark:text-amber-400">{t("staleHint")}</p>
          )}
          {change.rationale && <p className="text-sm">{change.rationale}</p>}
          {change.expected_effect && (
            <p className="text-sm">{t("expects", { effect: change.expected_effect })}</p>
          )}
          <EvidenceList items={change.evidence} dropped={change.evidence_dropped} />
          {change.description !== change.current_description && (
            <TextDiff before={change.current_description ?? ""} after={change.description ?? ""} />
          )}
          <div className="bg-muted max-h-80 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
            <TextDiff before={change.current_content} after={change.content} />
          </div>
        </div>
      )}
    </div>
  );
}
