"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Badge, Button, Card, CardContent, Textarea } from "@/components/ui";
import type { Hunk, HunkDecision } from "@/types/authoring";
import { EvidenceList } from "./evidence-list";
import { TextDiff } from "./text-diff";

/**
 * One suggestion: what it changes, why, and the decision on it.
 *
 * Pending, it offers Accept, Edit and Dismiss - Edit accepts the person's own
 * wording instead. Decided, it offers Undo while that still fits the draft. A
 * suggestion whose passage was edited away says so and offers only Dismiss.
 */
export function SuggestionCard({
  hunk,
  canEdit,
  busy,
  onDecide,
}: {
  hunk: Hunk;
  canEdit: boolean;
  busy: boolean;
  onDecide: (decision: HunkDecision) => void;
}) {
  const t = useTranslations("authoring.suggestion");
  const [editing, setEditing] = useState<string | null>(null);
  const tool = hunk.kind === "tool_override";
  const pending = hunk.status === "pending";

  return (
    <Card data-testid="suggestion">
      <CardContent className="space-y-3 pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">
            {tool ? t("tool", { tool: hunk.tool_id ?? "" }) : t("instructions")}
          </Badge>
          {hunk.origin === "verify" && <Badge variant="outline">{t("fromVerify")}</Badge>}
          {hunk.status !== "pending" && (
            <Badge variant="outline">{t(`status.${hunk.status}`)}</Badge>
          )}
          {!hunk.applies && hunk.status !== "dismissed" && (
            <Badge variant="warning">{t("stale")}</Badge>
          )}
        </div>
        {tool ? (
          <div className="space-y-2">
            {hunk.new_name !== null && (
              <TextDiff before={hunk.base_name ?? hunk.tool_id ?? ""} after={hunk.new_name} />
            )}
            {hunk.new_description !== null && (
              <TextDiff before={hunk.base_description ?? ""} after={hunk.new_description} />
            )}
          </div>
        ) : editing !== null ? (
          <Textarea
            aria-label={t("editLabel")}
            value={editing}
            onChange={(event) => setEditing(event.target.value)}
            rows={4}
          />
        ) : (
          <TextDiff
            context={hunk.context_before}
            before={hunk.old_text}
            after={
              hunk.status === "accepted" ? (hunk.accepted_text ?? hunk.new_text) : hunk.new_text
            }
            trailing={hunk.context_after}
          />
        )}
        <p className="text-sm">{hunk.rationale}</p>
        <EvidenceList items={hunk.evidence} dropped={hunk.evidence_dropped} />
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            {pending && editing !== null && (
              <>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => onDecide({ action: "accept", text: editing })}
                >
                  {t("saveAndAccept")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                  {t("cancel")}
                </Button>
              </>
            )}
            {pending && editing === null && (
              <>
                {hunk.applies && (
                  <Button size="sm" disabled={busy} onClick={() => onDecide({ action: "accept" })}>
                    {t("accept")}
                  </Button>
                )}
                {hunk.applies && !tool && (
                  <Button size="sm" variant="outline" onClick={() => setEditing(hunk.new_text)}>
                    {t("edit")}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => onDecide({ action: "dismiss" })}
                >
                  {t("dismiss")}
                </Button>
              </>
            )}
            {!pending && (hunk.applies || hunk.status === "dismissed") && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => onDecide({ action: "undo" })}
              >
                {t("undo")}
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
