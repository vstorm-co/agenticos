"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Input } from "@/components/ui";

/**
 * The workflow's name in the editor's header, renamed where it stands: a click
 * turns it into a field, Enter or leaving it saves, Escape keeps the old name.
 * Someone who may not edit the workflow sees plain text.
 */
export function WorkflowTitle({
  name,
  canEdit,
  onRename,
}: {
  name: string;
  canEdit: boolean;
  onRename: (name: string) => void;
}) {
  const t = useTranslations("pages.workflows");
  const [draft, setDraft] = useState<string | null>(null);

  if (!canEdit) return <>{name}</>;
  if (draft === null) {
    return (
      <button
        type="button"
        title={t("renameHint")}
        className="hover:bg-accent/60 -mx-1.5 rounded-md px-1.5 text-left"
        onClick={() => setDraft(name)}
      >
        {name}
      </button>
    );
  }

  const finish = () => {
    const next = draft.trim();
    setDraft(null);
    if (next !== "" && next !== name) onRename(next);
  };
  return (
    <Input
      aria-label={t("renameLabel")}
      value={draft}
      maxLength={128}
      className="h-9 max-w-md text-xl font-semibold"
      // Opened by the click that asked for it, so taking focus is expected.
      // eslint-disable-next-line jsx-a11y/no-autofocus
      autoFocus
      onChange={(event) => setDraft(event.target.value)}
      onBlur={finish}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") setDraft(null);
      }}
    />
  );
}
