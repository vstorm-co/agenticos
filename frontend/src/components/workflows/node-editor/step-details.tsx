"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Input, Label, Switch, Textarea } from "@/components/ui";
import type { NodeInstance, Uuid } from "@/lib/workflows/types";

type Details = Partial<Pick<NodeInstance, "label" | "notes" | "disabled">>;

/**
 * A step's own name and note, and the switch that takes it out of the run.
 *
 * Both texts are written when the field is left, like every other text in the
 * editor, so a step renamed letter by letter is one undoable edit. An empty name
 * falls back to the step's name from the catalog. The switch is not offered to
 * the trigger or to a step that decides which way the run goes: neither can be
 * skipped (publishing refuses it), so there is nothing to switch.
 */
export function StepDetails({
  node,
  catalogName,
  canSwitchOff,
  disabled,
  onChange,
}: {
  node: NodeInstance;
  catalogName: string;
  canSwitchOff: boolean;
  /** Read-only: every field reads, none writes. */
  disabled: boolean;
  onChange: (nodeId: Uuid, details: Details) => void;
}) {
  const t = useTranslations("workflows");
  const [label, setLabel] = useState(node.label ?? "");
  const [notes, setNotes] = useState(node.notes ?? "");
  const [noting, setNoting] = useState(false);
  const [seen, setSeen] = useState(node);
  if (node !== seen) {
    setSeen(node);
    setLabel(node.label ?? "");
    setNotes(node.notes ?? "");
  }

  const commitLabel = () => {
    const next = label.trim() || null;
    if (next !== (node.label ?? null)) onChange(node.id, { label: next });
  };
  const commitNotes = () => {
    const next = notes.trim() || null;
    if (next !== (node.notes ?? null)) onChange(node.id, { notes: next });
  };

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1.5">
        <Label htmlFor="step-label">{t("stepName")}</Label>
        <Input
          id="step-label"
          value={label}
          maxLength={64}
          placeholder={catalogName}
          disabled={disabled}
          onChange={(event) => setLabel(event.target.value)}
          onBlur={commitLabel}
        />
      </div>
      {canSwitchOff && (
        <div className="flex items-end gap-2 pb-2">
          <Switch
            id="step-disabled"
            checked={node.disabled === true}
            disabled={disabled}
            onCheckedChange={(off) => onChange(node.id, { disabled: off })}
          />
          <Label htmlFor="step-disabled" className="font-normal">
            {t("stepSwitchedOff")}
          </Label>
        </div>
      )}
      {!noting && !node.notes ? (
        !disabled && (
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground justify-self-start text-sm sm:col-span-2"
            onClick={() => setNoting(true)}
          >
            {t("stepAddNote")}
          </button>
        )
      ) : (
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="step-notes">{t("stepNotes")}</Label>
          <Textarea
            id="step-notes"
            value={notes}
            rows={2}
            maxLength={2000}
            placeholder={t("stepNotesPlaceholder")}
            disabled={disabled}
            onChange={(event) => setNotes(event.target.value)}
            onBlur={commitNotes}
          />
        </div>
      )}
    </div>
  );
}
