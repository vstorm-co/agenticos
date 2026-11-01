"use client";

import { useState } from "react";
import type { KeyboardEvent, RefObject } from "react";
import { Code2, Eye } from "lucide-react";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { CodeArea } from "@/components/ui/code-area";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

interface MarkdownEditorProps {
  value: string;
  /** The new text, and where the caret is in it. */
  onChange: (next: string, caret: number) => void;
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
  /**
   * Whether what is in it was refused, and where the refusal is written.
   *
   * A generated form has to be able to show a generated refusal, and it puts the
   * sentence in a paragraph under the field - which a screen reader reaches only
   * if the control points at it. The instructions field has no such path today;
   * a capability's configuration does, so the wiring travels with the component
   * rather than being lost by whoever reuses it.
   */
  invalid?: boolean;
  describedBy?: string;
  /**
   * A hard cap on what can be typed, where the field has one.
   *
   * The browser's own limit, not a validation message: a field whose length the
   * server refuses should not let somebody write past it and find out on submit.
   * It applies to the source textarea, which is the only place text is entered.
   */
  maxLength?: number;
  /** Keys in the source view, for a caller completing what is being typed. */
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  /**
   * Source or preview, held by the caller - which then draws
   * `MarkdownModeToggle` itself, in a header of its own. Absent, the editor
   * keeps the mode and draws the toggle above the field.
   */
  mode?: MarkdownMode;
  /**
   * Draw an image in the preview as a link rather than loading it - for text the
   * person did not write, where an image URL is a request the author chose to
   * make from this browser.
   */
  inertImages?: boolean;
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
export type MarkdownMode = "source" | "preview";

export function MarkdownEditor({
  value,
  onChange,
  label,
  invalid,
  describedBy,
  placeholder,
  rows = 10,
  disabled,
  id,
  textareaRef,
  maxLength,
  onKeyDown,
  mode: controlledMode,
  inertImages,
}: MarkdownEditorProps) {
  const t = useTranslations("ui");
  const [ownMode, setOwnMode] = useState<MarkdownMode>("source");
  const mode = controlledMode ?? ownMode;

  return (
    <div className="space-y-1.5">
      {/* The toggle sits above the field rather than in a bar inside it: a
          strip reading "Markdown | Source Preview" boxed the text a second
          time, inside whatever card already held it. A caller with a header
          of its own takes the mode in hand and puts the toggle there. */}
      {controlledMode === undefined && (
        <div className="flex justify-end">
          <MarkdownModeToggle mode={mode} onChange={setOwnMode} />
        </div>
      )}
      {mode === "source" ? (
        // The source shows its own structure - headings bold, markers dimmed,
        // `{{variables}}` as tokens - and stays plain Markdown underneath. Sized
        // by rows like the textarea it replaced, and still draggable taller.
        <div
          className="border-input bg-background resize-y overflow-hidden rounded-xl border"
          style={{ height: `calc(${rows} * 1.5rem + 1.5rem + 2px)` }}
        >
          <CodeArea
            name="field.md"
            textareaRef={textareaRef}
            id={id}
            maxLength={maxLength}
            aria-label={label}
            invalid={invalid}
            describedBy={describedBy}
            value={value}
            onChange={onChange}
            onKeyDown={onKeyDown}
            disabled={disabled}
            placeholder={placeholder}
            className="rounded-xl"
          />
        </div>
      ) : (
        // As tall as the source it stands in for, and scrolled inside: a
        // preview that grew to the whole document pushed the rest of the page
        // a screen down and lost the field's shape.
        <div
          role="region"
          aria-label={t("labelPreview", { label })}
          className="border-input resize-y overflow-auto rounded-xl border p-3"
          style={{ height: `calc(${rows} * 1.5rem + 1.5rem + 2px)` }}
        >
          {value.trim() === "" ? (
            <p className="text-muted-foreground text-sm">{t("nothingWrittenYet")}</p>
          ) : (
            <MarkdownContent content={value} inertImages={inertImages} />
          )}
        </div>
      )}
    </div>
  );
}

/** Source or preview, as a small segmented control - inside a field or a header. */
export function MarkdownModeToggle({
  mode,
  onChange,
}: {
  mode: MarkdownMode;
  onChange: (mode: MarkdownMode) => void;
}) {
  const t = useTranslations("ui");
  return (
    <div className="border-input flex w-fit items-center gap-0.5 rounded-lg border p-0.5">
      <ModeButton
        icon={Code2}
        label={t("source")}
        active={mode === "source"}
        onClick={() => onChange("source")}
      />
      <ModeButton
        icon={Eye}
        label={t("preview")}
        active={mode === "preview"}
        onClick={() => onChange("preview")}
      />
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
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors",
        active ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}
