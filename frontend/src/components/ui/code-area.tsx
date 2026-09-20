"use client";

import hljs from "highlight.js/lib/core";
import markdown from "highlight.js/lib/languages/markdown";
import { useMemo, useRef, type ChangeEvent, type UIEvent } from "react";

import { cn } from "@/lib/utils";

// One language, registered once. Everything this pane edits is prose with
// markup in it; a file that is really code lives in a workspace, where the
// viewer already highlights it.
hljs.registerLanguage("markdown", markdown);

export interface CodeAreaProps {
  value: string;
  onChange?: (next: string) => void;
  readOnly?: boolean;
  /** The file being edited - its extension is what picks the language. */
  name: string;
  "aria-label": string;
  className?: string;
}

/** Markdown, or nothing - a `.txt` file has no syntax to colour. */
function languageOf(name: string): "markdown" | null {
  return /\.(md|markdown|mdx)$/i.test(name) ? "markdown" : null;
}

/**
 * A textarea that shows its own syntax.
 *
 * The plain one it replaces made a long `AGENTS.md` a wall of identical grey:
 * the headings that give it structure looked like the sentences under them, so
 * the shape of the file was invisible in the only view that lets you change it.
 *
 * Drawn as two layers, because a textarea cannot hold colour: the highlighted
 * copy underneath and the real control on top with transparent text and a
 * visible caret. The two are kept in register by giving them the same font,
 * padding and wrapping, and by copying the scroll position across - anything
 * else and the colours drift off the words by a line.
 *
 * `highlight.js` escapes what it highlights, which is what makes the underlay
 * safe to set as HTML; nothing here hands it markup of its own.
 */
export function CodeArea({
  value,
  onChange,
  readOnly,
  name,
  "aria-label": label,
  className,
}: CodeAreaProps) {
  const underlay = useRef<HTMLPreElement>(null);
  const language = languageOf(name);

  const html = useMemo(() => {
    // A trailing newline, so the last line of the file has a line to sit on:
    // without it the underlay is one row shorter than the textarea and every
    // colour above the fold looks correct while the bottom one is missing.
    const text = `${value}\n`;
    return language === null
      ? escapeHtml(text)
      : hljs.highlight(text, { language, ignoreIllegals: true }).value;
  }, [value, language]);

  const sync = (event: UIEvent<HTMLTextAreaElement>) => {
    const pane = underlay.current;
    if (pane === null) return;
    pane.scrollTop = event.currentTarget.scrollTop;
    pane.scrollLeft = event.currentTarget.scrollLeft;
  };

  const shared = "p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words";

  return (
    // Both layers are absolutely positioned against this box, so they are the
    // same rectangle by construction. The textarea used to be the only one laid
    // out normally, which made it as tall as its own two default rows while the
    // underlay showed the whole file - the text below the second line was a
    // picture you could not type into.
    <div className={cn("bg-background relative h-full rounded-md border", className)}>
      <pre
        ref={underlay}
        aria-hidden
        className={cn(shared, "hljs pointer-events-none absolute inset-0 m-0 overflow-hidden")}
        dangerouslySetInnerHTML={{ __html: html }}
      />
      <textarea
        value={value}
        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange?.(event.target.value)}
        onScroll={sync}
        readOnly={readOnly}
        spellCheck={false}
        aria-label={label}
        className={cn(
          shared,
          "caret-foreground text-foreground/0 absolute inset-0 h-full w-full resize-none overflow-auto bg-transparent outline-none",
          "focus-visible:ring-ring rounded-md focus-visible:ring-1",
        )}
      />
    </div>
  );
}

/** For a file with no language: the underlay still has to be safe to set. */
function escapeHtml(text: string): string {
  return text.replace(/[&<>]/g, (char) =>
    char === "&" ? "&amp;" : char === "<" ? "&lt;" : "&gt;",
  );
}
