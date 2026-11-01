"use client";

import { useTranslations } from "next-intl";

import { expectedEffect } from "@/lib/authoring-text";
import type { AuthoringRequest, SuggestionBatch } from "@/types/authoring";
import type { EntryActions } from "./change-groups";
import { CheckResults } from "./check-result";
import { SuggestionTabs } from "./suggestion-tabs";

/**
 * A batch of suggestions: what they are expected to change, the eval runs that
 * checked them, and each suggestion and new-skill idea, in To review and Decided.
 *
 * The expected effect is the assistant's prediction, shown beside the checks so
 * a person can compare it with what the runs found. A batch a newer request
 * replaced is read-only.
 */
export function SuggestionList({
  batch,
  request,
  agentId,
  actions,
}: {
  batch: SuggestionBatch | null;
  /** The latest finished request, whose report holds the new-skill ideas. */
  request: AuthoringRequest | null;
  agentId: string;
  actions: Omit<EntryActions, "open">;
}) {
  const t = useTranslations("authoring.batch");
  const effect = batch ? expectedEffect(batch, (count) => t("fromEvidence", { count })) : "";
  return (
    <div className="space-y-3">
      {batch !== null && batch.status !== "open" && (
        <p className="text-muted-foreground text-sm">{t(`closed.${batch.status}`)}</p>
      )}
      {effect !== "" && (
        <p className="text-sm">
          <span className="font-medium">{t("expected")}</span> {effect}
        </p>
      )}
      {batch !== null && batch.check_eval_run_ids.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm">{t("checks")}</p>
          <CheckResults agentId={agentId} runIds={batch.check_eval_run_ids} />
        </div>
      )}
      <SuggestionTabs batch={batch} request={request} actions={actions} />
    </div>
  );
}
