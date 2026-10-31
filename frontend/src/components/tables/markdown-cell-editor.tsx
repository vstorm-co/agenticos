"use client";

import { useRef, useState, type FocusEvent } from "react";
import { Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui";
import { CodeArea } from "@/components/ui/code-area";
import { DIALOG_BODY, DIALOG_BROAD, DIALOG_FILL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { markdownDocument } from "@/lib/markdown-document";

/** A Markdown source and reader over the same buffered cell; never serializes the document. */
export function MarkdownCellEditor({
  fill,
  id,
  label,
  value,
  onChange,
  onCommit,
  disabled,
  invalid,
  describedBy,
}: {
  id: string;
  fill?: boolean;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onCommit: () => void;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
}) {
  const t = useTranslations("tables.markdown");
  const [preview, setPreview] = useState(Boolean(disabled));
  const [expanded, setExpanded] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const parts = markdownDocument(value);

  const commitOnLeave = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget;
    if (
      next instanceof Node &&
      (event.currentTarget.contains(next) || dialog.current?.contains(next))
    )
      return;
    onCommit();
  };

  const editor = (fieldId: string) => (
    <>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex gap-1" role="group" aria-label={label}>
          <Button
            type="button"
            variant={preview ? "ghost" : "secondary"}
            size="sm"
            aria-pressed={!preview}
            onClick={() => setPreview(false)}
          >
            {t("write")}
          </Button>
          <Button
            type="button"
            variant={preview ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={preview}
            onClick={() => setPreview(true)}
          >
            {t("preview")}
          </Button>
        </div>
        {fieldId === id && (
          <DialogTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("expand")}
              title={t("expand")}
            >
              <Maximize2 className="size-4" aria-hidden />
            </Button>
          </DialogTrigger>
        )}
      </div>
      {preview ? (
        <div className="min-h-56 min-w-0 flex-1 space-y-4 overflow-auto p-4">
          {parts.frontmatter !== null && (
            <details className="rounded-lg border px-3 py-2">
              <summary className="text-muted-foreground cursor-pointer text-xs font-medium">
                {t("properties")}
              </summary>
              <pre className="mt-2 overflow-x-auto text-xs whitespace-pre-wrap">
                {parts.frontmatter}
              </pre>
            </details>
          )}
          {parts.body.trim() ? (
            <MarkdownContent content={parts.body} inertImages />
          ) : (
            <p className="text-muted-foreground text-sm">{t("empty")}</p>
          )}
        </div>
      ) : (
        <CodeArea
          id={fieldId}
          aria-label={label}
          name="note.md"
          value={value}
          onChange={onChange}
          disabled={disabled}
          readOnly={disabled}
          invalid={invalid}
          describedBy={describedBy}
          className="min-h-56 flex-1"
        />
      )}
    </>
  );

  return (
    // The group observes focus leaving child controls; it does not take keyboard input.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div role="group" aria-label={label} onBlur={commitOnLeave} className="min-w-0 space-y-2">
      <Dialog
        open={expanded}
        onOpenChange={(open) => {
          if (!open) onCommit();
          setExpanded(open);
        }}
      >
        <div
          className={cn(
            "flex min-w-0 flex-col overflow-hidden rounded-lg border",
            fill && "h-[max(24rem,calc(100dvh-22rem))]",
          )}
        >
          {editor(id)}
        </div>
        <p className="text-muted-foreground text-xs">{t("hint")}</p>
        <DialogContent ref={dialog} className={`${DIALOG_BROAD} ${DIALOG_FILL}`}>
          <DialogHeader>
            <DialogTitle>{label}</DialogTitle>
            <DialogDescription>{t("hint")}</DialogDescription>
          </DialogHeader>
          <div className={`${DIALOG_BODY} flex flex-col`}>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border">
              {editor(`${id}-expanded`)}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              onClick={() => {
                onCommit();
                setExpanded(false);
              }}
            >
              {t("done")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
