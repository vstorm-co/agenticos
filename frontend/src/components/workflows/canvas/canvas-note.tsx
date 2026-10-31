"use client";

import { useRef, useState } from "react";
import { NodeResizer, type Node, type NodeProps } from "@xyflow/react";
import { Palette, Pencil, Maximize2, Scaling } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  Textarea,
} from "@/components/ui";
import { DIALOG_BROAD, DIALOG_COLUMN, DIALOG_BODY } from "@/lib/dialog-sizes";
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
 * its palette button - a warning in red, a to-do in yellow. It is never
 * a step - no port, nothing runs it.
 */
/**
 * The note's tint, folded behind one palette button so a selected note shows a
 * single control rather than a row of dots. The swatches roll out to its left,
 * inside the note, and fold back on a pick, on Escape or once focus leaves them.
 */
function NoteColorPicker({
  color,
  shown,
  onPick,
}: {
  color: NoteColor;
  /** Whether the button shows without a hover - the note is selected. */
  shown: boolean;
  onPick: (color: NoteColor) => void;
}) {
  const t = useTranslations("workflows");
  const [open, setOpen] = useState(false);
  const palette = useRef<HTMLButtonElement>(null);
  // Folding unmounts the swatch that holds focus; without this it falls to the page.
  const fold = () => {
    palette.current?.focus();
    setOpen(false);
  };
  return (
    // Hears focus leaving the swatches and Escape inside them; the buttons are the controls.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      className="nodrag absolute right-1.5 bottom-1.5 flex items-center gap-1"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as HTMLElement | null))
          setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") fold();
      }}
    >
      {open && (
        <div
          role="radiogroup"
          aria-label={t("noteColor")}
          className="bg-background/90 animate-in fade-in-0 slide-in-from-right-2 flex gap-1.5 rounded-full border px-1.5 py-1 shadow-sm"
        >
          {COLORS.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={color === option}
              aria-label={t(`noteColors.${option}`)}
              title={t(`noteColors.${option}`)}
              onClick={() => {
                onPick(option);
                fold();
              }}
              className={cn(
                "focus-visible:ring-ring size-4 rounded-full outline-none focus-visible:ring-2",
                TINTS[option].swatch,
                color === option &&
                  "ring-foreground/70 ring-offset-background ring-2 ring-offset-1",
              )}
            />
          ))}
        </div>
      )}
      <button
        ref={palette}
        type="button"
        aria-label={t("noteColor")}
        aria-expanded={open}
        title={t("noteColor")}
        onClick={() => setOpen(!open)}
        className={cn(
          "text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded p-1 outline-none focus-visible:ring-2",
          shown || open
            ? "opacity-100"
            : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
        )}
      >
        <Palette aria-hidden="true" className="size-3.5" />
      </button>
    </div>
  );
}

export function CanvasNoteCard({ data, selected }: NodeProps<CanvasNoteNode>) {
  const t = useTranslations("workflows");
  const updateNote = useWorkflowEditorStore((state) => state.updateNote);
  const { note, readOnly } = data;
  const color = note.color ?? "default";
  const [draft, setDraft] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const expandButton = useRef<HTMLButtonElement>(null);

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
        "group text-foreground relative h-full w-full overflow-hidden rounded-lg border px-3 pt-9 pb-3 text-sm shadow-sm",
        TINTS[color].card,
        selected && "ring-primary/40 ring-2",
      )}
      onDoubleClick={() => !readOnly && !expanded && draft === null && setDraft(note.text)}
    >
      {!readOnly && (
        <NodeResizer
          isVisible={selected}
          minWidth={180}
          minHeight={100}
          handleStyle={{ width: 9, height: 9 }}
        />
      )}
      <div
        className="nodrag bg-background/90 absolute top-1.5 left-1.5 z-10 flex items-center gap-1 rounded-md p-0.5 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100 data-[selected=true]:opacity-100"
        data-selected={selected}
      >
        <Button
          variant="ghost"
          size="icon"
          className="size-6"
          ref={expandButton}
          aria-label={t("noteExpand")}
          onClick={() => {
            setDraft(draft ?? note.text);
            setExpanded(true);
          }}
        >
          <Maximize2 className="size-3.5" />
        </Button>
        {!readOnly && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-6" aria-label={t("noteSize")}>
                <Scaling className="size-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {(
                [
                  ["noteSizeSmall", 240, 140],
                  ["noteSizeWide", 480, 180],
                  ["noteSizeLarge", 480, 360],
                ] as const
              ).map(([key, width, height]) => (
                <DropdownMenuItem key={key} onSelect={() => updateNote(note.id, { width, height })}>
                  {t(key)}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <Dialog
        open={expanded}
        onOpenChange={(open) => {
          if (!open) {
            if (!readOnly) finish();
            else setDraft(null);
          }
          setExpanded(open);
        }}
      >
        <DialogContent
          className={`${DIALOG_BROAD} ${DIALOG_COLUMN}`}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            expandButton.current?.focus();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("noteLabel")}</DialogTitle>
          </DialogHeader>
          <div className={DIALOG_BODY}>
            {readOnly ? (
              <MarkdownContent content={note.text} inertImages />
            ) : (
              <Textarea
                aria-label={t("noteLabel")}
                value={draft ?? note.text}
                onChange={(event) => setDraft(event.target.value)}
                maxLength={4000}
                className="min-h-80 resize-y"
              />
            )}
          </div>
          <DialogFooter>
            <Button
              onClick={() => {
                if (!readOnly) finish();
                else setDraft(null);
                setExpanded(false);
              }}
            >
              {t("nodeEditorDone")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
      {!readOnly && draft === null && (
        <NoteColorPicker
          color={color}
          shown={selected}
          onPick={(option) => color !== option && updateNote(note.id, { color: option })}
        />
      )}
      {draft !== null && !expanded ? (
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
