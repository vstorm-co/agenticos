"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { Maximize2, Trash2 } from "lucide-react";

import { EditorTextLoading } from "./editor-loading";
import { FileTextView } from "./file-render";
import { Button } from "@/components/ui";
import { MarkdownModeToggle } from "@/components/ui/markdown-mode-toggle";
import { CodeArea } from "@/components/ui/code-area";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { DIALOG_WINDOW } from "@/lib/dialog-sizes";
import { resolveFileKind } from "@/lib/file-kinds";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

/**
 * A named piece of text, read or edited, filling whatever it is given.
 *
 * The write-side counterpart of `FileViewer`: that one fetches a stored file and
 * shows it, this one is handed a draft somebody may be halfway through typing.
 * Rendered by default and editable behind a toggle, because these are read far
 * more often than they are written - and Markdown read as raw asterisks is the
 * thing this pane exists to stop.
 *
 * Presentational on purpose, and in `components/files` rather than in the domain
 * that first needed it: a skill's `SKILL.md`, one of its references and a
 * context file are the same object to a reader, so they get the same pane. It
 * lived in `components/skills` and `/context` had a bare textarea instead, which
 * is how one product grew two ideas of what editing a file looks like.
 */
export function FileEditor({
  name,
  label,
  content,
  loading,
  canEdit,
  onChange,
  onDelete,
  footer,
  header,
  toolbar,
  initialMode = "source",
  placeholder,
  className,
}: {
  name: string;
  /** What the pane calls the file, where its name is not what a reader knows it by. */
  label?: string;
  content: string;
  loading?: boolean;
  canEdit: boolean;
  /** Absent for a read-only pane - there is nothing for it to be called with. */
  onChange?: (next: string) => void;
  onDelete?: () => void;
  footer?: ReactNode;
  /** Anything the owner wants above the content - the body's own fields. */
  header?: ReactNode;
  /** Owner controls that belong beside source/preview, rather than above the editor. */
  toolbar?: ReactNode;
  /**
   * Which half opens first. A browser of files somebody else wrote opens on the
   * preview; a pane somebody came to *write* in opens on the source, where a
   * rendering of what they have not typed yet is a picture of an empty file.
   */
  initialMode?: "preview" | "source";
  /** Shown in the source half while the file is empty. */
  placeholder?: string;
  /**
   * For a floor, where the pane's parent has no height of its own to fill: it
   * grows into whatever it is given, and an empty draft inside a dialog sized by
   * its content is otherwise a strip between a header and a footer.
   */
  className?: string;
}) {
  const t = useTranslations("files");
  const tc = useTranslations("common");
  const tu = useTranslations("ui");
  const [mode, setMode] = useState<"preview" | "source">(initialMode);
  const [expanded, setExpanded] = useState(false);
  const called = label ?? name;

  const pane = (
    <div
      className={cn(
        "bg-background flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border",
        expanded && "overflow-hidden rounded-2xl border-0",
        className,
      )}
    >
      <div
        className={cn(
          "bg-muted/70 flex flex-wrap items-center gap-2 border-b px-3 py-2",
          expanded && "pr-14",
        )}
      >
        <span className={cn("min-w-0 flex-1 truncate text-xs", label === undefined && "font-mono")}>
          {called}
        </span>
        {!expanded && toolbar}
        <MarkdownModeToggle mode={mode} onChange={setMode} />
        {!expanded && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            data-tour="text-editor-expand"
            aria-label={tu("expandEditor", { label: called })}
            onClick={() => setExpanded(true)}
          >
            <Maximize2 className="size-4" aria-hidden />
          </Button>
        )}
        {onDelete && canEdit && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={tc("removeNamed", { name: called })}
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>

      {header && <div className="space-y-1.5 border-b px-3 py-2">{header}</div>}

      {/* The source half brings its own padding, because both of its layers
          have to carry the same one to stay in register. */}
      <div className={cn("min-h-0 flex-1 overflow-auto", mode === "source" ? "p-0" : "p-3")}>
        {loading ? (
          <div role="status" aria-busy="true" aria-label={tc("loading")}>
            <EditorTextLoading />
          </div>
        ) : mode === "source" ? (
          // Fills the pane rather than sitting in it: a fixed-row box inside a
          // tall panel leaves the text in a letterbox with dead space under it.
          <CodeArea
            value={content}
            onChange={onChange ? (next) => onChange(next) : undefined}
            readOnly={!canEdit}
            placeholder={placeholder}
            name={name}
            aria-label={t("namedSource", { name: called })}
            className="min-h-[14rem]"
          />
        ) : (
          // The shared renderer, which is what makes a skill's `references/api.md`
          // read the same as the same file in a workspace. It is `FileTextView` and
          // not `FileViewer` because there is nothing to fetch: the content is
          // a draft somebody may be halfway through editing.
          <FileTextView kind={resolveFileKind(name)} name={name} text={content} />
        )}
      </div>

      {footer && <div className="flex items-center gap-2 border-t px-3 py-2">{footer}</div>}
    </div>
  );
  return (
    <>
      {!expanded && pane}
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent
          className={cn(DIALOG_WINDOW, "gap-0 p-0 sm:p-0")}
          aria-describedby={undefined}
        >
          <DialogTitle className="sr-only">{called}</DialogTitle>
          {pane}
        </DialogContent>
      </Dialog>
    </>
  );
}
