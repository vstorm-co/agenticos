"use client";

import { useTranslations } from "next-intl";

import { expectedEffect } from "@/lib/authoring-text";
import type { Hunk, HunkDecision, SuggestionBatch } from "@/types/authoring";
import { CheckResults } from "./check-result";
import { SuggestionCard } from "./suggestion-card";

/**
 * A batch of suggestions: what they are expected to change, the eval runs that
 * checked them, and each suggestion with its decision - waiting ones first.
 *
 * The expected effect is the assistant's prediction, shown beside the checks so
 * a person can compare it with what the runs found. A closed batch - replaced by
 * a newer request, or published - is read-only.
 */
export function SuggestionList({
  batch,
  agentId,
  busy,
  onDecide,
}: {
  batch: SuggestionBatch;
  agentId: string;
  busy: boolean;
  onDecide: (hunk: Hunk, decision: HunkDecision) => void;
}) {
  const t = useTranslations("authoring.batch");
  const open = batch.status === "open";
  const effect = expectedEffect(batch, (count) => t("fromEvidence", { count }));
  const ordered = [...batch.hunks].sort(
    (a, b) => Number(a.status !== "pending") - Number(b.status !== "pending"),
  );
  return (
    <div className="space-y-3">
      {!open && <p className="text-muted-foreground text-sm">{t(`closed.${batch.status}`)}</p>}
      {effect !== "" && (
        <p className="text-sm">
          <span className="font-medium">{t("expected")}</span> {effect}
        </p>
      )}
      {batch.check_eval_run_ids.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm">{t("checks")}</p>
          <CheckResults agentId={agentId} runIds={batch.check_eval_run_ids} />
        </div>
      )}
      {ordered.map((hunk) => (
        <SuggestionCard
          key={`${hunk.id}-${hunk.status}`}
          hunk={hunk}
          canEdit={open}
          busy={busy}
          onDecide={(decision) => onDecide(hunk, decision)}
        />
      ))}
    </div>
  );
}
