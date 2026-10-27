"use client";

import { useState } from "react";
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
export function AttemptChanges({ session, editable }: { session: Improvement; editable: boolean }) {
  const t = useTranslations("improvement.attemptChanges");
  const tErrors = useTranslations("errors");
  const { changes, isLoading, error } = useImprovementChanges(session.agent_id, session.id);
  const actions = useImprovement(session.agent_id, session.id);
  const [failure, setFailure] = useState<string | null>(null);
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
  return (
    <div className="space-y-4">
      {changes.map((hunk, index) => {
        const ticked = included.includes(hunk.id);
        const last = ticked && included.length === 1;
        return (
          <div key={hunk.id} className="space-y-2">
            {editable && (
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
            {hunk.edited_text && <StateBadge tone="neutral">{t("edited")}</StateBadge>}
            {editable && hunk.kind === "instructions" && (
              <Rewording
                hunk={hunk}
                number={index + 1}
                busy={actions.editChange.isPending}
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
  onSave,
}: {
  hunk: Hunk;
  number: number;
  busy: boolean;
  /** Whether the server kept it; the editor stays open when it did not. */
  onSave: (text: string | null) => Promise<boolean>;
}) {
  const t = useTranslations("improvement.attemptChanges");
  const [draft, setDraft] = useState<string | null>(null);
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
