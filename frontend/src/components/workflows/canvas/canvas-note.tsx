"use client";

import { useState } from "react";
import { NodeResizer, type Node, type NodeProps } from "@xyflow/react";
import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Textarea } from "@/components/ui";
import type { CanvasNote } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

export type CanvasNoteNode = Node<{ note: CanvasNote; readOnly: boolean }, "note">;

export const NOTE_WIDTH = 240;
export const NOTE_HEIGHT = 140;

/**
 * A note on the canvas: markdown beside the steps, for whoever reads the
 * workflow next. Double-click to write in it, click away to keep it; drag it by
 * its body and resize it from its corners once selected. It is never a step -
 * no port, nothing runs it.
 */
export function CanvasNoteCard({ data, selected }: NodeProps<CanvasNoteNode>) {
  const t = useTranslations("workflows");
  const updateNote = useWorkflowEditorStore((state) => state.updateNote);
  const { note, readOnly } = data;
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
        "group bg-muted/70 text-foreground relative h-full w-full overflow-hidden rounded-lg border p-3 text-sm shadow-sm",
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
