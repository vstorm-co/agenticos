"use client";

import { useRef, useState } from "react";
import { NodeResizeControl, type Node, type NodeProps } from "@xyflow/react";
import { Palette, Pencil, Maximize2, Scaling, MoreHorizontal, MoveDownRight } from "lucide-react";
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
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
  DropdownMenuRadioItem,
  DropdownMenuRadioGroup,
  DropdownMenuSeparator,
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
  default: { card: "bg-card border-border/60", swatch: "bg-muted-foreground/40" },
  yellow: {
    card: "bg-[color-mix(in_oklab,var(--color-amber-500)_16%,var(--color-card))] border-amber-500/20",
    swatch: "bg-amber-400",
  },
  green: {
    card: "bg-[color-mix(in_oklab,var(--color-emerald-500)_16%,var(--color-card))] border-emerald-500/20",
    swatch: "bg-emerald-400",
  },
  blue: {
    card: "bg-[color-mix(in_oklab,var(--color-sky-500)_16%,var(--color-card))] border-sky-500/20",
    swatch: "bg-sky-400",
  },
  purple: {
    card: "bg-[color-mix(in_oklab,var(--color-violet-500)_16%,var(--color-card))] border-violet-500/20",
    swatch: "bg-violet-400",
  },
  red: {
    card: "bg-[color-mix(in_oklab,var(--color-rose-500)_16%,var(--color-card))] border-rose-500/20",
    swatch: "bg-rose-400",
  },
};
const COLORS = Object.keys(TINTS) as NoteColor[];

export const NOTE_WIDTH = 240;
export const NOTE_HEIGHT = 140;

export function CanvasNoteCard({ data, selected }: NodeProps<CanvasNoteNode>) {
  const t = useTranslations("workflows");
  const updateNote = useWorkflowEditorStore((state) => state.updateNote);
  const { note, readOnly } = data;
  const color = note.color ?? "default";
  const [draft, setDraft] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const actionsButton = useRef<HTMLButtonElement>(null);

  const finish = () => {
    if (draft !== null && draft !== note.text) updateNote(note.id, { text: draft });
    setDraft(null);
  };

  return (
    // Double-click is the shortcut; the action menu is keyboard accessible.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      data-note-id={note.id}
      className={cn(
        "group text-foreground relative h-full w-full overflow-hidden rounded-xl border px-4 pt-10 pb-4 text-sm shadow-sm",
        TINTS[color].card,
        selected && "ring-foreground/15 ring-1",
      )}
      onDoubleClick={() => !readOnly && !expanded && draft === null && setDraft(note.text)}
    >
      {!readOnly && selected && (
        <NodeResizeControl
          position="bottom-right"
          minWidth={180}
          minHeight={100}
          className="text-muted-foreground/60 hover:text-foreground !top-auto !right-1 !bottom-1 !left-auto !size-5 !translate-x-0 !translate-y-0 !rounded !border-0 !bg-transparent"
        >
          <MoveDownRight aria-hidden="true" className="size-3.5" />
        </NodeResizeControl>
      )}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            ref={actionsButton}
            variant="ghost"
            size="icon"
            aria-label={t("noteActions")}
            className="nodrag touch:opacity-100 absolute top-1.5 right-1.5 z-10 size-7 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"
          >
            <MoreHorizontal aria-hidden="true" className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          onCloseAutoFocus={(event) => {
            if (draft !== null || expanded) event.preventDefault();
          }}
        >
          {!readOnly && (
            <DropdownMenuItem onSelect={() => setDraft(note.text)}>
              <Pencil className="size-4" />
              {t("noteEdit")}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            onSelect={() => {
              setDraft(draft ?? note.text);
              setExpanded(true);
            }}
          >
            <Maximize2 className="size-4" />
            {t("noteExpand")}
          </DropdownMenuItem>
          {!readOnly && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <Palette className="mr-2 size-4" />
                  {t("noteColor")}
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  <DropdownMenuRadioGroup value={color}>
                    {COLORS.map((option) => (
                      <DropdownMenuRadioItem
                        key={option}
                        value={option}
                        onSelect={() => {
                          if (color !== option) updateNote(note.id, { color: option });
                        }}
                      >
                        <span
                          aria-hidden="true"
                          className={cn("mr-2 size-3 rounded-full", TINTS[option].swatch)}
                        />
                        {t(`noteColors.${option}`)}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuSubContent>
              </DropdownMenuSub>
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <Scaling className="mr-2 size-4" />
                  {t("noteSize")}
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  {(
                    [
                      ["noteSizeSmall", 240, 140],
                      ["noteSizeWide", 480, 180],
                      ["noteSizeLarge", 480, 360],
                    ] as const
                  ).map(([key, width, height]) => (
                    <DropdownMenuItem
                      key={key}
                      onSelect={() => updateNote(note.id, { width, height })}
                    >
                      {t(key)}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
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
            actionsButton.current?.focus();
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
