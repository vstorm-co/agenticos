"use client";

import { GitCompare } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { Button, LineDiff } from "@/components/ui";
import type { WorkflowStepDecision } from "@/lib/workflows/types";
import { formatDateTime } from "@/lib/utils";

/**
 * Above a finished approval step's output in a run: who decided and when, and -
 * when the approver edited the proposal - what they changed.
 */
export function ApprovalVerdict({
  approval,
  output,
}: {
  approval: WorkflowStepDecision;
  output: Record<string, unknown> | null;
}) {
  const t = useTranslations("workflows");
  const tr = useTranslations("pages.runs");
  const locale = useLocale();
  const [showChanges, setShowChanges] = useState(false);
  const time = approval.decided_at === null ? null : formatDateTime(approval.decided_at, locale);
  const decided = approval.status === "approved" || approval.status === "rejected";
  const original = typeof output?.original === "string" ? output.original : null;
  const final = typeof output?.final === "string" ? output.final : null;
  const edited = output?.edited === true && original !== null && final !== null;

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium" data-testid="approval-verdict">
        {decided
          ? t("stepApprovalDecided", {
              status: approval.status,
              name: approval.decided_by_name ?? "",
              known: approval.decided_by_name === null ? "no" : "yes",
              time: time ?? "",
            })
          : t("stepApprovalUndecided", { status: approval.status })}
      </p>
      {edited && (
        <>
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={showChanges}
            onClick={() => setShowChanges((shown) => !shown)}
          >
            <GitCompare className="size-3.5" />
            {showChanges ? tr("stepApprovalHideChanges") : tr("stepApprovalShowChanges")}
          </Button>
          {showChanges && (
            <LineDiff
              before={original}
              after={final}
              identicalLabel={tr("stepApprovalNoChanges")}
              unchangedLabel={(count) => tr("stepApprovalUnchangedLines", { count })}
              tooLongLabel={tr("stepApprovalDiffTooLong")}
            />
          )}
        </>
      )}
    </div>
  );
}
