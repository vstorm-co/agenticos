"use client";

import { Loader2, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useCaseKeyDraft } from "@/hooks/use-case-key-draft";
import type { DocumentKey } from "@/types/datasets";

/** How many drafted keys are named before "and N more". */
const SHOWN_KEYS = 5;

/**
 * Listing the facts of a case's saved reference answer, for its keys check.
 *
 * The key extractor reads the answer as saved, so an unsaved change to it must be
 * saved first. Using the list fills the case's keys check for the person to
 * review and save; it never saves anything itself.
 */
export function KeyDraftPanel({
  datasetId,
  caseId,
  savedReference,
  editedReference,
  onUse,
}: {
  datasetId: string;
  caseId: string;
  savedReference: string | null;
  editedReference: string;
  onUse: (keys: DocumentKey[]) => void;
}) {
  const t = useTranslations("datasets.keyDraft");
  const { draft, loading, error, start, starting, dismiss } = useCaseKeyDraft(datasetId, caseId, {
    enabled: true,
  });
  const saved = (savedReference ?? "").trim();
  const unsaved = editedReference.trim() !== saved;
  const blocked = saved === "" ? t("noReference") : unsaved ? t("saveFirst") : null;

  if (loading) {
    return (
      <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
        <Loader2 className="size-4 animate-spin" />
        {t("loading")}
      </p>
    );
  }
  if (error) {
    return (
      <p className="text-destructive text-sm" role="alert">
        {t("unreadable")}
      </p>
    );
  }
  if (draft?.status === "running") {
    return (
      <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
        <Loader2 className="size-4 animate-spin" />
        {t("running")}
      </p>
    );
  }
  if (draft?.status === "ready") {
    const named = draft.keys.slice(0, SHOWN_KEYS).map((key) => key.key);
    return (
      <div className="space-y-2 rounded-lg border p-3 text-sm" role="status">
        <p>
          {draft.keys.length === 0
            ? t("none")
            : t("found", {
                count: draft.keys.length,
                names: named.join(", "),
                more: Math.max(draft.keys.length - SHOWN_KEYS, 0),
              })}
        </p>
        <div className="flex flex-wrap gap-2">
          {draft.keys.length > 0 && (
            <Button
              type="button"
              size="sm"
              disabled={blocked !== null}
              onClick={() => {
                onUse(draft.keys);
                dismiss();
              }}
            >
              {t("use")}
            </Button>
          )}
          <Button type="button" size="sm" variant="ghost" onClick={dismiss}>
            {t("dismiss")}
          </Button>
        </div>
        {blocked !== null && <p className="text-muted-foreground">{blocked}</p>}
      </div>
    );
  }
  return (
    <div className="space-y-2 text-sm">
      {draft?.status === "failed" && (
        <p className="text-destructive" role="alert">
          {t("failed", { error: draft.error ?? "" })}
        </p>
      )}
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={blocked !== null || starting}
        onClick={start}
      >
        <Sparkles className="size-4" />
        {draft?.status === "failed" ? t("retry") : t("start")}
      </Button>
      {blocked !== null && <p className="text-muted-foreground">{blocked}</p>}
    </div>
  );
}
