"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

/** The longest description; `WorkflowUpdate.description` in the service. */
const MAX_DESCRIPTION = 2000;

/**
 * The workflow's description under its name in the editor's header, edited where
 * it stands as the name is: a click turns it into a field, leaving it saves,
 * Escape keeps the old text, and clearing it removes the description. Enter
 * starts a new line; Ctrl+Enter or Cmd+Enter saves. Someone who may not edit the
 * workflow sees plain text, or nothing when there is none.
 */
export function WorkflowDescription({
  description,
  canEdit,
  onChange,
}: {
  description: string | null;
  canEdit: boolean;
  onChange: (description: string | null) => void;
}) {
  const t = useTranslations("pages.workflows");
  const [draft, setDraft] = useState<string | null>(null);

  if (!canEdit) return description;
  if (draft === null) {
    return (
      <button
        type="button"
        title={t("describeHint")}
        className="hover:bg-accent/60 -mx-1.5 rounded-md px-1.5 text-left"
        onClick={() => setDraft(description ?? "")}
      >
        {description ?? <span className="italic">{t("describe")}</span>}
      </button>
    );
  }

  const finish = () => {
    const next = draft.trim() || null;
    setDraft(null);
    if (next !== description) onChange(next);
  };
  return (
    // The text itself, made editable - not a form field dropped into the header:
    // the same size and colour, growing with what is written.
    <textarea
      aria-label={t("describeLabel")}
      value={draft}
      maxLength={MAX_DESCRIPTION}
      rows={1}
      placeholder={t("describe")}
      className="bg-accent/60 placeholder:text-muted-foreground/70 focus-visible:ring-ring/40 -mx-1.5 block [field-sizing:content] w-[calc(100%+0.75rem)] max-w-2xl resize-none rounded-md px-1.5 text-sm leading-relaxed outline-none focus-visible:ring-1"
      // Opened by the click that asked for it, so taking focus is expected.
      // eslint-disable-next-line jsx-a11y/no-autofocus
      autoFocus
      onChange={(event) => setDraft(event.target.value)}
      onBlur={finish}
      onKeyDown={(event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          // Handled here, so the editor's own Ctrl+Enter - Run - leaves it alone.
          event.preventDefault();
          event.currentTarget.blur();
        }
        if (event.key === "Escape") setDraft(null);
      }}
    />
  );
}
