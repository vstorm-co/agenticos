"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Input, Label, Switch, Textarea } from "@/components/ui";
import type { NodeInstance, Uuid } from "@/lib/workflows/types";

type Details = Partial<Pick<NodeInstance, "label" | "notes" | "disabled">>;
type OnChange = (nodeId: Uuid, details: Details) => void;

/**
 * A step's name in its dialog's header, renamed where it stands, as a workflow's
 * is in the editor's: a click turns it into a field, Enter or leaving it saves,
 * Escape keeps the old name, and an emptied one falls back to the catalog's.
 * Written when the field is left, so a step renamed letter by letter is one
 * undoable edit. Read-only, it is plain text.
 */
export function StepName({
  node,
  name,
  catalogName,
  disabled,
  onChange,
}: {
  node: NodeInstance;
  /** What the step is called now: its own name, or the catalog's. */
  name: string;
  catalogName: string;
  disabled: boolean;
  onChange: OnChange;
}) {
  const t = useTranslations("workflows");
  const [draft, setDraft] = useState<string | null>(null);

  if (disabled) return <>{name}</>;
  if (draft === null) {
    return (
      <button
        type="button"
        title={t("stepRenameHint")}
        className="hover:bg-accent/60 -mx-1.5 rounded-md px-1.5 text-left"
        onClick={() => setDraft(node.label ?? "")}
      >
        {name}
      </button>
    );
  }

  const finish = () => {
    const next = draft.trim() || null;
    setDraft(null);
    if (next !== (node.label ?? null)) onChange(node.id, { label: next });
  };
  return (
    <Input
      aria-label={t("stepName")}
      value={draft}
      maxLength={64}
      placeholder={catalogName}
      className="h-8 max-w-sm text-base font-semibold"
      // Opened by the click that asked for it, so taking focus is expected.
      // eslint-disable-next-line jsx-a11y/no-autofocus
      autoFocus
      onChange={(event) => setDraft(event.target.value)}
      onBlur={finish}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") {
          // The dialog closes on Escape too; this one only ends the rename.
          event.stopPropagation();
          setDraft(null);
        }
      }}
    />
  );
}

/**
 * Whether the run carries out this step - off, it is skipped and hands on what
 * came into it. Put as a yes, "Run this step", rather than as "Switched off", so
 * the switch reads the same way its state does. Not offered to the trigger or to
 * a step that decides which way the run goes: neither can be skipped (publishing
 * refuses it), so there is nothing to switch.
 */
export function StepSwitch({ node, onChange }: { node: NodeInstance; onChange: OnChange }) {
  const t = useTranslations("workflows");
  return (
    <div className="flex items-center gap-2" title={t("stepRunsHint")}>
      <Switch
        id="step-runs"
        checked={node.disabled !== true}
        onCheckedChange={(on) => onChange(node.id, { disabled: !on })}
      />
      <Label htmlFor="step-runs" className="font-normal">
        {t("stepRuns")}
      </Label>
    </div>
  );
}

/**
 * A line for whoever edits the workflow next, shown on the step's card. Offered
 * as a link until there is one, and written when the field is left.
 */
export function StepNote({
  node,
  disabled,
  onChange,
}: {
  node: NodeInstance;
  disabled: boolean;
  onChange: OnChange;
}) {
  const t = useTranslations("workflows");
  const [notes, setNotes] = useState(node.notes ?? "");
  const [noting, setNoting] = useState(false);
  const [seen, setSeen] = useState(node);
  if (node !== seen) {
    setSeen(node);
    setNotes(node.notes ?? "");
  }

  const commit = () => {
    const next = notes.trim() || null;
    if (next !== (node.notes ?? null)) onChange(node.id, { notes: next });
  };

  if (!noting && !node.notes) {
    return disabled ? null : (
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground text-sm"
        onClick={() => setNoting(true)}
      >
        {t("stepAddNote")}
      </button>
    );
  }
  return (
    <div className="space-y-1.5">
      <Label htmlFor="step-notes">{t("stepNotes")}</Label>
      <Textarea
        id="step-notes"
        value={notes}
        rows={2}
        maxLength={2000}
        placeholder={t("stepNotesPlaceholder")}
        disabled={disabled}
        onChange={(event) => setNotes(event.target.value)}
        onBlur={commit}
      />
    </div>
  );
}
