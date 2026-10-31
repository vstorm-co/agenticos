"use client";

import { useRef, useState, type FocusEvent } from "react";
import { Bold, Italic, Link2, ImagePlus, Video, Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui";
import { DIALOG_BODY, DIALOG_WINDOW } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { DocumentProperties, type DocumentMetadata } from "./document-properties";
import { withDocumentBody } from "@/lib/document-properties";
import { DocumentTemplates } from "./document-templates";
import { MarkdownInput } from "./markdown-input";
import { markdownDocument } from "@/lib/markdown-document";

/** Metadata and Markdown share one buffered cell; body edits preserve the header. */
export function MarkdownCellEditor({
  tableId,
  columnId,
  onCommitValue,
  fill,
  showMetadata = true,
  metadata,
  template,
  id,
  label,
  value,
  onChange,
  onCommit,
  disabled,
  invalid,
  describedBy,
}: {
  tableId?: string;
  columnId?: string;
  onCommitValue?: (value: string) => void;
  metadata?: DocumentMetadata;
  template?: string;
  id: string;
  fill?: boolean;
  showMetadata?: boolean;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onCommit: () => void;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
}) {
  const t = useTranslations("tables.markdown");
  const [preview, setPreview] = useState(
    Boolean(disabled) ||
      (!fill && Boolean(metadata?.created_at && markdownDocument(value).body.trim())),
  );
  const [layoutMode, setLayoutMode] = useState(fill);
  if (layoutMode !== fill) {
    setLayoutMode(fill);
    setPreview(
      Boolean(disabled) ||
        (!fill && Boolean(metadata?.created_at && markdownDocument(value).body.trim())),
    );
  }
  const [expanded, setExpanded] = useState(false);
  const [replacement, setReplacement] = useState<string | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const parts = markdownDocument(value);

  const commitOnLeave = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget;
    if (
      next instanceof Node &&
      (event.currentTarget.contains(next) ||
        dialog.current?.contains(next) ||
        (next instanceof Element &&
          next.closest("[data-document-templates]")?.getAttribute("data-document-templates") ===
            columnId))
    )
      return;
    onCommit();
  };

  const insert = (fieldId: string, before: string, after: string) => {
    const textarea = document.getElementById(fieldId);
    if (!(textarea instanceof HTMLTextAreaElement)) {
      setPreview(false);
      return;
    }
    const start = textarea.selectionStart,
      end = textarea.selectionEnd;
    const selection = parts.body.slice(start, end);
    onChange(
      withDocumentBody(
        value,
        parts.body.slice(0, start) + before + selection + after + parts.body.slice(end),
      ),
    );
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(start + before.length, end + before.length);
    });
  };
  const editor = (fieldId: string) => (
    <>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 px-2 py-2">
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
        {!disabled && !preview && (
          <div className="flex items-center gap-0.5">
            {[
              { key: "bold", icon: Bold, before: "**", after: "**" },
              { key: "italic", icon: Italic, before: "_", after: "_" },
              { key: "link", icon: Link2, before: "[", after: "](https://)" },
              { key: "image", icon: ImagePlus, before: "![", after: "](https://)" },
              { key: "video", icon: Video, before: "[", after: "](https://example.com/video.mp4)" },
            ].map(({ key, icon: Icon, before, after }) => (
              <Button
                key={key}
                type="button"
                size="icon"
                variant="ghost"
                className="size-8"
                aria-label={t(key)}
                title={t(key)}
                onClick={() => insert(fieldId, before, after)}
              >
                <Icon className="size-4" aria-hidden />
              </Button>
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-1">
          {!disabled && tableId && columnId && (
            <DocumentTemplates
              tableId={tableId}
              columnId={columnId}
              body={parts.body}
              onApply={(body) => {
                if (parts.body.trim()) setReplacement(body);
                else onChange(withDocumentBody(value, body));
              }}
            />
          )}
          {!disabled && !(tableId && columnId) && template !== undefined && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                if (parts.body.trim()) setReplacement(template ?? "");
                else onChange(withDocumentBody(value, template));
              }}
            >
              {t("applyTemplate")}
            </Button>
          )}
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
      </div>
      {showMetadata && <DocumentProperties metadata={metadata} />}
      {preview ? (
        <div className="min-h-72 min-w-0 flex-1 space-y-4 overflow-auto px-4 py-6 sm:px-6">
          {parts.body.trim() ? (
            <MarkdownContent content={parts.body} documentMedia />
          ) : (
            <p className="text-muted-foreground text-sm">{t("empty")}</p>
          )}
        </div>
      ) : (
        <MarkdownInput
          tableId={tableId}
          id={fieldId}
          aria-label={label}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          value={parts.body}
          onValueChange={(body) => onChange(withDocumentBody(value, body))}
          onImageInserted={(body) => onCommitValue?.(withDocumentBody(value, body))}
          disabled={disabled}
          readOnly={disabled}
          maxLength={100000}
          spellCheck
          className="min-h-72 flex-1 resize-y rounded-none border-0 bg-transparent px-4 py-6 text-base leading-7 shadow-none focus-visible:ring-0 sm:px-6"
        />
      )}
    </>
  );

  return (
    // The group observes focus leaving child controls; it does not take keyboard input.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div role="group" aria-label={label} onBlur={commitOnLeave} className="min-w-0 space-y-2">
      <ConfirmDialog
        open={replacement !== null}
        onOpenChange={(open) => {
          if (!open) setReplacement(null);
        }}
        title={t("replaceTitle")}
        description={t("replaceDescription")}
        confirmLabel={t("useTemplate")}
        onConfirm={() => {
          onChange(withDocumentBody(value, replacement ?? ""));
          setReplacement(null);
          requestAnimationFrame(() =>
            document.getElementById(expanded ? `${id}-expanded` : id)?.focus(),
          );
        }}
      />
      <Dialog
        open={expanded}
        onOpenChange={(open) => {
          if (!open) onCommit();
          if (open && !disabled) setPreview(false);
          setExpanded(open);
        }}
      >
        <div
          className={cn(
            "flex min-w-0 flex-col overflow-hidden",
            fill && "h-[max(32rem,calc(100dvh-22rem))] overflow-y-auto",
          )}
        >
          {editor(id)}
        </div>
        {!preview && <p className="text-muted-foreground text-xs">{t("hint")}</p>}
        <DialogContent ref={dialog} className={DIALOG_WINDOW}>
          <DialogHeader>
            <DialogTitle>{label}</DialogTitle>
            <DialogDescription>{t("hint")}</DialogDescription>
          </DialogHeader>
          <div className={`${DIALOG_BODY} flex flex-col`}>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
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
