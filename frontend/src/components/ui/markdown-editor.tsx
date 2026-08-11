"use client";

import { useState } from "react";
import type { RefObject } from "react";
import { Code2, Eye } from "lucide-react";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

interface MarkdownEditorProps {
  value: string;
  onChange: (next: string) => void;
  /** The control's accessible name. Required: a placeholder is not a label. */
  label: string;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  id?: string;
  /**
   * The source textarea, for a caller that has to write into it.
   *
   * Only one thing needs it - inserting a placeholder where the caret is,
   * rather than at the end - and that is worth a prop: the alternative is
   * reaching for the element by id from outside the component, which is the
   * same coupling with nothing naming it.
   */
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
}

/**
 * Markdown, edited as source or read as Markdown.
 *
 * The skill editor has had this toggle since `SKILL.md` stopped being rendered
 * as raw asterisks; this is the same control, extracted so anything else holding
 * Markdown can have it. It is not the skill editor's `FileViewer` - that one is
 * a *file*, with a name, a delete button and a footer, and none of those mean
 * anything for a field on a form.
 *
 * The source view is the default, unlike the file viewer's. A field somebody
 * opened a form to edit should be editable when they get there; a file somebody
 * clicked in a tree is one they came to read.
 */
export function MarkdownEditor({
  value,
  onChange,
  label,
  placeholder,
  rows = 10,
  disabled,
  id,
  textareaRef,
}: MarkdownEditorProps) {
  const t = useTranslations("ui");
  const [mode, setMode] = useState<"source" | "preview">("source");

  return (
    <div className="border-input rounded-md border">
      <div className="border-input flex items-center justify-between gap-2 border-b px-2 py-1.5">
        <span className="text-muted-foreground text-xs">{t("markdown")}</span>
        <div className="border-input flex items-center gap-0.5 rounded-md border p-0.5">
          <ModeButton
            icon={Code2}
            label={t("source")}
            active={mode === "source"}
            onClick={() => setMode("source")}
          />
          <ModeButton
            icon={Eye}
            label={t("preview")}
            active={mode === "preview"}
            onClick={() => setMode("preview")}
          />
        </div>
      </div>

      {mode === "source" ? (
        // Borderless: the wrapper draws the border now, and two nested ones read
        // as a field inside a field.
        <Textarea
          ref={textareaRef}
          id={id}
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={rows}
          disabled={disabled}
          placeholder={placeholder}
          className="resize-y rounded-none border-0 font-mono text-sm focus-visible:ring-0"
        />
      ) : (
        <div
          // Named the same as the field it previews, so the two halves of one
          // control are not two unrelated regions to a screen reader.
          role="region"
          aria-label={t("labelPreview", { label })}
          className="overflow-auto p-3"
          // Inline, not a class: Tailwind generates utilities by scanning the
          // source, so a class built from a prop at runtime is a class that was
          // never compiled. Matching the textarea's height keeps the panel from
          // collapsing when the toggle is flipped on a short draft.
          style={{ minHeight: `${rows * 1.5}rem` }}
        >
          {value.trim() === "" ? (
            <p className="text-muted-foreground text-sm">{t("nothingWrittenYet")}</p>
          ) : (
            <MarkdownContent content={value} />
          )}
        </div>
      )}
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
