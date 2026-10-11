"use client";

import { useState } from "react";
import { NodeResizer, type Node, type NodeProps } from "@xyflow/react";
import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Textarea } from "@/components/ui";
import type { CanvasNote, NoteColor } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

export type CanvasNoteNode = Node<{ note: CanvasNote; readOnly: boolean }, "note">;

/** Each tint as the card draws it, and as its swatch shows it. */
// Opaque - the card's own colour mixed with the tint - so the canvas's grid does
// not show through the text.
const TINTS: Record<NoteColor, { card: string; swatch: string }> = {
  default: { card: "bg-muted border-border", swatch: "bg-muted-foreground/40" },
  yellow: {
    card: "bg-[color-mix(in_oklab,var(--color-amber-500)_16%,var(--color-card))] border-amber-500/40",
    swatch: "bg-amber-400",
  },
  green: {
    card: "bg-[color-mix(in_oklab,var(--color-emerald-500)_16%,var(--color-card))] border-emerald-500/40",
    swatch: "bg-emerald-400",
  },
  blue: {
    card: "bg-[color-mix(in_oklab,var(--color-sky-500)_16%,var(--color-card))] border-sky-500/40",
    swatch: "bg-sky-400",
  },
  purple: {
    card: "bg-[color-mix(in_oklab,var(--color-violet-500)_16%,var(--color-card))] border-violet-500/40",
    swatch: "bg-violet-400",
  },
  red: {
    card: "bg-[color-mix(in_oklab,var(--color-rose-500)_16%,var(--color-card))] border-rose-500/40",
    swatch: "bg-rose-400",
  },
};
const COLORS = Object.keys(TINTS) as NoteColor[];

export const NOTE_WIDTH = 240;
export const NOTE_HEIGHT = 140;

/**
 * A note on the canvas: markdown beside the steps, for whoever reads the
 * workflow next. Double-click to write in it, click away to keep it; drag it by
 * its body and resize it from its corners once selected, and pick its tint from
 * the swatches it then shows - a warning in red, a to-do in yellow. It is never
 * a step - no port, nothing runs it.
 */
export function CanvasNoteCard({ data, selected }: NodeProps<CanvasNoteNode>) {
  const t = useTranslations("workflows");
  const updateNote = useWorkflowEditorStore((state) => state.updateNote);
  const { note, readOnly } = data;
  const color = note.color ?? "default";
  const [draft, setDraft] = useState<string | null>(null);

  const finish = () => {
    if (draft !== null && draft !== note.text) updateNote(note.id, { text: draft });
    setDraft(null);
  };

  return (
    // A double-click is the shortcut; the Edit button beside the text is the way
    // a keyboard gets there.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      data-note-id={note.id}
      className={cn(
        "group text-foreground relative h-full w-full overflow-hidden rounded-lg border p-3 text-sm shadow-sm",
        TINTS[color].card,
        selected && "ring-primary/40 ring-2",
      )}
      onDoubleClick={() => !readOnly && setDraft(note.text)}
    >
      {!readOnly && <NodeResizer isVisible={selected} minWidth={120} minHeight={60} />}
      {!readOnly && draft === null && (
        <button
          type="button"
          aria-label={t("noteEdit")}
          title={t("noteEdit")}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring absolute top-1.5 right-1.5 rounded p-1 opacity-0 outline-none group-hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-2"
          onClick={() => setDraft(note.text)}
        >
          <Pencil aria-hidden="true" className="size-3.5" />
        </button>
      )}
      {!readOnly && selected && draft === null && (
        <div
          role="radiogroup"
          aria-label={t("noteColor")}
          className="nodrag absolute right-1.5 bottom-1.5 flex gap-1"
        >
          {COLORS.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={color === option}
              aria-label={t(`noteColors.${option}`)}
              title={t(`noteColors.${option}`)}
              onClick={() => color !== option && updateNote(note.id, { color: option })}
              className={cn(
                "focus-visible:ring-ring size-3.5 rounded-full outline-none focus-visible:ring-2",
                TINTS[option].swatch,
                color === option &&
                  "ring-foreground/70 ring-offset-background ring-2 ring-offset-1",
              )}
            />
          ))}
        </div>
      )}
      {draft !== null ? (
        <Textarea
          aria-label={t("noteLabel")}
          value={draft}
          maxLength={4000}
          // Opened by the double-click that asked for it.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          className="nodrag nowheel h-full resize-none border-0 bg-transparent p-0 shadow-none focus-visible:ring-0"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={finish}
          onKeyDown={(event) => {
            if (event.key === "Escape") setDraft(null);
          }}
        />
      ) : note.text.trim() === "" ? (
        <p className="text-muted-foreground">{readOnly ? "" : t("noteEmpty")}</p>
      ) : (
        <div className="prose-sm max-w-none">
          <MarkdownContent content={note.text} inertImages />
        </div>
      )}
    </div>
  );
}
