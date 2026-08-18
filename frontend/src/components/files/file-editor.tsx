"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { Code2, Eye, Trash2 } from "lucide-react";

import { FileTextView } from "./file-render";
import { Button, Textarea } from "@/components/ui";
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
  content,
  loading,
  canEdit,
  onChange,
  onDelete,
  footer,
  header,
  className,
}: {
  name: string;
  content: string;
  loading?: boolean;
  canEdit: boolean;
  /** Absent for a read-only pane - there is nothing for it to be called with. */
  onChange?: (next: string) => void;
  onDelete?: () => void;
  footer?: ReactNode;
  /** Anything the owner wants above the content - the body's own fields. */
  header?: ReactNode;
  /**
   * For a floor, where the pane's parent has no height of its own to fill: it
   * grows into whatever it is given, and an empty draft inside a dialog sized by
   * its content is otherwise a strip between a header and a footer.
   */
  className?: string;
}) {
  const t = useTranslations("files");
  const tc = useTranslations("common");
  const [mode, setMode] = useState<"preview" | "source">("preview");

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col rounded-md border", className)}>
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <span className="min-w-0 flex-1 truncate font-mono text-xs">{name}</span>
        <div className="flex items-center gap-0.5 rounded-md border p-0.5">
          <ModeButton
            icon={Eye}
            label={t("preview")}
            active={mode === "preview"}
            onClick={() => setMode("preview")}
          />
          <ModeButton
            icon={Code2}
            label={t("source")}
            active={mode === "source"}
            onClick={() => setMode("source")}
          />
        </div>
        {onDelete && canEdit && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={tc("removeNamed", { name })}
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>

      {header && <div className="space-y-1.5 border-b px-3 py-2">{header}</div>}

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {loading ? (
          <p className="text-muted-foreground text-xs">{tc("loading")}</p>
        ) : mode === "source" ? (
          // Fills the pane rather than sitting in it: a fixed-row box inside a
          // tall panel leaves the text in a letterbox with dead space under it.
          <Textarea
            value={content}
            onChange={(event) => onChange?.(event.target.value)}
            readOnly={!canEdit}
            className="h-full min-h-[16rem] resize-none font-mono text-xs"
            aria-label={t("namedSource", { name })}
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
}

function ModeButton({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: typeof Eye;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors",
        active ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}
