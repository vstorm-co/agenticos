"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Checkbox, Textarea } from "@/components/ui";
import { ChangePreview } from "@/components/authoring/result-dialog";
import { useImprovement, useImprovementChanges } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import { currentAttempt } from "@/lib/improvement-steps";
import type { Hunk } from "@/types/authoring";
import type { Improvement } from "@/types/improvement";
import { StateBadge } from "./widgets";

/**
 * The current attempt's changes. At the stop after Changes a person ticks which to
 * test and may reword one, which is what the check then measures; nothing reaches
 * the draft until the result is accepted. While they are being checked they are
 * only read.
 */
export function AttemptChanges({
  session,
  editable,
  onEditing,
}: {
  session: Improvement;
  editable: boolean;
  /** Whether a rewording is open with text not saved yet. */
  onEditing?: (editing: boolean) => void;
}) {
  const t = useTranslations("improvement.attemptChanges");
  const tErrors = useTranslations("errors");
  const { changes, isLoading, error } = useImprovementChanges(session.agent_id, session.id);
  const actions = useImprovement(session.agent_id, session.id);
  const [failure, setFailure] = useState<string | null>(null);
  const [unsaved, setUnsaved] = useState<string[]>([]);
  useEffect(() => {
    onEditing?.(unsaved.length > 0);
    return () => onEditing?.(false);
  }, [unsaved.length, onEditing]);
  const markUnsaved = useCallback(
    (hunkId: string, open: boolean) =>
      setUnsaved((ids) => (open ? [...ids, hunkId] : ids.filter((id) => id !== hunkId))),
    [],
  );
  const included = currentAttempt(session)?.included_hunk_ids ?? [];
  if (error) return <p role="alert">{getErrorMessage(error, tErrors)}</p>;
  if (isLoading) return <p role="status">{t("loading")}</p>;
  if (changes.length === 0) return <p className="text-muted-foreground text-sm">{t("none")}</p>;
  async function act(action: () => Promise<unknown>): Promise<boolean> {
    setFailure(null);
    try {
      await action();
      return true;
    } catch (reason) {
      setFailure(getErrorMessage(reason, tErrors));
      return false;
    }
  }
  const single = changes.length === 1;
  return (
    <div className="space-y-4">
      {editable && single && <p className="text-sm">{t("single")}</p>}
      {changes.map((hunk, index) => {
        const ticked = included.includes(hunk.id);
        const last = ticked && included.length === 1;
        return (
          <div key={hunk.id} className="space-y-2">
            {editable && !single && (
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={ticked}
                  disabled={last || actions.selectChanges.isPending}
                  aria-label={t("include", { number: index + 1 })}
                  onCheckedChange={(checked) =>
                    void act(() =>
                      actions.selectChanges.mutateAsync(
                        checked === true
                          ? [...included, hunk.id]
                          : included.filter((id) => id !== hunk.id),
                      ),
                    )
                  }
                />
                {t("includeLabel")}
                {last && <span className="text-muted-foreground text-xs">{t("lastOne")}</span>}
              </label>
            )}
            <ChangePreview
              hunk={hunk.edited_text ? { ...hunk, new_text: hunk.edited_text } : hunk}
              conversations={{}}
            />
            {hunk.edited_text && (
              <div className="space-y-1">
                <StateBadge tone="neutral">{t("edited")}</StateBadge>
                <p className="text-muted-foreground text-xs">{t("editedReason")}</p>
              </div>
            )}
            {editable && hunk.kind === "instructions" && (
              <Rewording
                hunk={hunk}
                number={index + 1}
                busy={actions.editChange.isPending}
                onUnsaved={markUnsaved}
                onSave={(text) =>
                  act(() => actions.editChange.mutateAsync({ hunkId: hunk.id, text }))
                }
              />
            )}
          </div>
        );
      })}
      {failure && (
        <p role="alert" className="text-destructive text-sm">
          {failure}
        </p>
      )}
    </div>
  );
}

function Rewording({
  hunk,
  number,
  busy,
  onUnsaved,
  onSave,
}: {
  hunk: Hunk;
  number: number;
  busy: boolean;
  onUnsaved: (hunkId: string, unsaved: boolean) => void;
  /** Whether the server kept it; the editor stays open when it did not. */
  onSave: (text: string | null) => Promise<boolean>;
}) {
  const t = useTranslations("improvement.attemptChanges");
  const [draft, setDraft] = useState<string | null>(null);
  const unsaved = draft !== null && draft !== (hunk.edited_text ?? hunk.new_text);
  useEffect(() => {
    if (!unsaved) return;
    onUnsaved(hunk.id, true);
    return () => onUnsaved(hunk.id, false);
  }, [unsaved, hunk.id, onUnsaved]);
  if (draft === null)
    return (
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setDraft(hunk.edited_text ?? hunk.new_text)}
        >
          {t("edit")}
        </Button>
        {hunk.edited_text && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void onSave(null)}>
            {t("revert")}
          </Button>
        )}
      </div>
    );
  return (
    <div className="space-y-2">
      <Textarea
        aria-label={t("wording", { number })}
        className="min-h-32 font-mono text-xs"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={busy || !draft.trim()}
          onClick={() =>
            void onSave(draft === hunk.new_text ? null : draft).then(
              (kept) => kept && setDraft(null),
            )
          }
        >
          {t("save")}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setDraft(null)}>
          {t("cancel")}
        </Button>
      </div>
    </div>
  );
}
