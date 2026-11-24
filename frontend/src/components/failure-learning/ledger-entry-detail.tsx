"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@/components/ui";
import type { LedgerEntryRead } from "@/lib/failure-learning-api";

/**
 * One entry: what the agent keeps doing wrong, the evidence it was judged
 * on, and the curation actions. Dismissing keeps the record - the reason is
 * appended to the summary, so the count's story survives the dismissal.
 * Resolving is not offered here: only applying a proposal resolves an
 * entry, and the server refuses a bare change to `resolved`.
 */
export function LedgerEntryDetail({
  entry,
  canEdit,
  onUpdate,
  onDelete,
}: {
  entry: LedgerEntryRead;
  canEdit: boolean;
  onUpdate: (entryId: string, input: { status?: "open" | "dismissed"; summary?: string }) => void;
  onDelete: (entryId: string) => void;
}) {
  const t = useTranslations("failureLearning");
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const evidence = entry.evidence as { count?: number; error_class?: string };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{entry.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm whitespace-pre-wrap">{entry.summary}</p>
        <p className="text-muted-foreground text-sm">
          {entry.pattern_key}
          {evidence.error_class ? ` · ${evidence.error_class}` : ""}
          {evidence.count !== undefined ? ` · ${t("occurrences", { count: evidence.count })}` : ""}
        </p>
        <Badge variant="secondary">{entry.status}</Badge>
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            {entry.status === "draft" && (
              <Button
                type="button"
                size="sm"
                onClick={() => onUpdate(entry.id, { status: "open" })}
              >
                {t("accept")}
              </Button>
            )}
            {entry.status !== "dismissed" && entry.status !== "resolved" && !dismissing && (
              <Button type="button" size="sm" variant="outline" onClick={() => setDismissing(true)}>
                {t("dismiss")}
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                if (confirmingDelete) onDelete(entry.id);
                else setConfirmingDelete(true);
              }}
            >
              {confirmingDelete ? t("confirmDelete") : t("deleteEntry")}
            </Button>
          </div>
        )}
        {dismissing && (
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              onUpdate(entry.id, {
                status: "dismissed",
                summary: `${entry.summary}\n\n${t("statusDismissed")}: ${reason.trim()}`,
              });
              setDismissing(false);
            }}
          >
            <Label htmlFor="dismiss-reason">{t("dismissReasonLabel")}</Label>
            <Input
              id="dismiss-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t("dismissReasonPlaceholder")}
              required
            />
            <Button type="submit" size="sm" disabled={reason.trim() === ""}>
              {t("dismiss")}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
