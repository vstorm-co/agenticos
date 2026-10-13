"use client";

import {
  useMemo,
  useRef,
  type ChangeEvent,
  type KeyboardEvent,
  type RefObject,
  type UIEvent,
} from "react";

import { markdownLines, type MdLine, type MdLineKind, type MdStyle } from "@/lib/markdown-tokens";
import { cn } from "@/lib/utils";

export interface CodeAreaProps {
  value: string;
  /** The new text, and where the caret is in it. */
  onChange?: (next: string, caret: number) => void;
  readOnly?: boolean;
  disabled?: boolean;
  /** Shown while the file is empty, in place of a blank rectangle. */
  placeholder?: string;
  /**
   * The file being edited - its extension is what picks the formatting. A field
   * that is not a file (an agent's instructions) passes a Markdown name.
   */
  name: string;
  "aria-label": string;
  id?: string;
  /** For a caller that has to put text at the caret - a variable from a list. */
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  maxLength?: number;
  invalid?: boolean;
  describedBy?: string;
  className?: string;
}

/** Markdown, or nothing - a `.txt` file has no syntax to show. */
function isMarkdown(name: string): boolean {
  return /\.(md|markdown|mdx)$/i.test(name);
}

/**
 * How each kind of piece reads. Colour, tint and stroke only - never size,
 * padding, weight or a different face - because the textarea above draws the
 * same characters in one font, and anything that changed a glyph's width would
 * walk the styling off the words. Bold is therefore a stroke around the regular
 * glyph rather than the bold one, which in a proportional face is wider.
 */
const PIECE: Record<MdStyle, string> = {
  plain: "",
  marker: "text-muted-foreground/70",
  strong: "text-foreground [-webkit-text-stroke:0.4px_currentColor]",
  emphasis: "italic",
  code: "rounded-sm bg-foreground/[0.07] text-rose-700 dark:text-rose-300",
  link: "text-sky-700 underline decoration-sky-700/30 underline-offset-2 dark:text-sky-300",
  url: "text-muted-foreground",
  variable: "rounded-sm bg-violet-500/12 text-violet-700 dark:text-violet-300",
};

const LINE: Record<MdLineKind, string> = {
  text: "",
  heading: "text-foreground [-webkit-text-stroke:0.65px_currentColor]",
  list: "",
  quote: "text-foreground/70",
  fence: "",
  code: "text-sky-800 dark:text-sky-300",
  rule: "",
  table: "",
};

/** The source, drawn with what each part of it is. */
function MarkdownSource({ lines }: { lines: MdLine[] }) {
  return lines.map((line, index) => (
    // Keyed by position: the lines have no identity of their own, and the
    // underlay is redrawn whole on every keystroke anyway.
    <span key={index} className={LINE[line.kind]}>
      {line.pieces.map((piece, at) => (
        <span key={at} className={PIECE[piece.style]}>
          {piece.text}
        </span>
      ))}
      {"\n"}
    </span>
  ));
}

/**
 * A textarea that shows its own structure.
 *
 * The plain one it replaces made a long prompt a wall of identical grey: the
 * headings that give it shape looked like the sentences under them. Here they
 * are bold, a bold word is bold, `code` sits on a tint, a `{{variable}}` reads
 * as one token, and the markers that make each - `#`, `**`, the backticks - stay
 * on the line, dimmed, so what is on screen is still exactly what is saved.
 *
 * Drawn as two layers, because a textarea cannot hold styling: the formatted
 * copy underneath and the real control on top with transparent text and a
 * visible caret. The two stay in register by sharing font, padding and wrapping,
 * by the underlay never changing a glyph's width, and by copying the scroll
 * position across.
 */
export function CodeArea({
  value,
  onChange,
  readOnly,
  disabled,
  placeholder,
  name,
  "aria-label": label,
  id,
  textareaRef,
  onKeyDown,
  maxLength,
  invalid,
  describedBy,
  className,
}: CodeAreaProps) {
  const underlay = useRef<HTMLPreElement>(null);
  const markdown = isMarkdown(name);
  const lines = useMemo(() => (markdown ? markdownLines(value) : null), [markdown, value]);

  const sync = (event: UIEvent<HTMLTextAreaElement>) => {
    const pane = underlay.current;
    if (pane === null) return;
    pane.scrollTop = event.currentTarget.scrollTop;
    pane.scrollLeft = event.currentTarget.scrollLeft;
  };

  // A text face, not a code one: what is written here is prose for a model to
  // read, and set in a terminal font it read as configuration.
  const shared = "px-4 py-3 font-sans text-[14px] leading-6 whitespace-pre-wrap break-words";

  return (
    // Both layers are absolutely positioned against this box, so they are the
    // same rectangle by construction. The focus ring lives on the box: the
    // textarea is transparent and edge to edge, so a ring of its own would
    // trace the inside of the pane twice.
    <div
      className={cn(
        "focus-within:ring-ring/60 relative h-full rounded-sm focus-within:ring-1 focus-within:ring-inset",
        invalid && "ring-destructive/60 ring-1 ring-inset",
        disabled && "opacity-60",
        className,
      )}
    >
      <pre
        ref={underlay}
        aria-hidden
        className={cn(
          shared,
          "text-foreground/85 pointer-events-none absolute inset-0 m-0 overflow-hidden",
        )}
      >
        {lines ? <MarkdownSource lines={lines} /> : value}
        {/* A last line to sit on, so the underlay is as tall as the textarea
            when the text ends in a newline. */}
        {lines ? null : "\n"}
      </pre>
      <textarea
        ref={textareaRef}
        id={id}
        value={value}
        onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
          onChange?.(event.target.value, event.target.selectionStart)
        }
        onKeyDown={onKeyDown}
        onScroll={sync}
        readOnly={readOnly}
        disabled={disabled}
        maxLength={maxLength}
        placeholder={placeholder}
        spellCheck={false}
        aria-label={label}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        className={cn(
          shared,
          // The text itself is invisible - the underlay is what you read - but
          // the placeholder has to be its own colour, or an empty file is a
          // blank rectangle with nothing to say what goes in it.
          "caret-foreground text-foreground/0 placeholder:text-muted-foreground absolute inset-0 h-full w-full resize-none overflow-auto bg-transparent outline-none selection:bg-sky-500/25",
        )}
      />
    </div>
  );
}
