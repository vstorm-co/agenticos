"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { copyableText, placeholderParts, type DraftField } from "@/lib/drafts";
import { MarkdownModeToggle, type MarkdownMode } from "@/components/ui/markdown-mode-toggle";
import { CopyButton } from "./copy-button";
import { MarkdownContent } from "./markdown-content";

/**
 * One part of a draft: its text as typed, a copy icon, and a hint of its format.
 * A markdown part can be previewed; images stay inert and copy always gives the source.
 */
export function DraftSegment({ field, named }: { field: DraftField; named: boolean }) {
  const [mode, setMode] = useState<MarkdownMode>("source");
  const prose = field.format === "text" || field.format === "markdown";
  const previewing = field.format === "markdown" && mode === "preview";
  const showName = named && field.name !== null;
  const clearToggle = field.format === "markdown" && !showName;
  return (
    <div
      data-draft-segment
      className="border-foreground/10 relative min-w-0 border-t px-3.5 py-2.5"
    >
      <div className="absolute top-2 right-2 flex items-center gap-1">
        {field.format === "markdown" && <MarkdownModeToggle mode={mode} onChange={setMode} />}
        <CopyButton text={copyableText(field.text)} className="opacity-100" />
      </div>
      {showName && <p className="text-muted-foreground mb-1 pr-36 text-xs">{field.name}</p>}
      {previewing ? (
        <div className={cn("min-w-0 pr-8 pb-4 text-sm break-words", clearToggle && "pt-8")}>
          <MarkdownContent content={field.text} inertImages bareCode />
        </div>
      ) : (
        <p
          className={cn(
            "pb-4 text-sm break-words whitespace-pre-wrap",
            "pr-8",
            clearToggle && "pt-8",
            !prose && "font-mono text-xs",
          )}
        >
          {placeholderParts(field.text, field.format).map((part, index) =>
            part.placeholder ? (
              <mark
                key={index}
                className="bg-transparent font-medium text-[var(--draft-placeholder-ink)] underline decoration-dotted underline-offset-2"
              >
                {part.text}
              </mark>
            ) : (
              part.text
            ),
          )}
        </p>
      )}
      <span className="text-muted-foreground absolute right-3.5 bottom-1.5 font-mono text-[10px]">
        {field.format}
      </span>
    </div>
  );
}
