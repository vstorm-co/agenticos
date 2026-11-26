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
  return (
    <div data-draft-segment className="border-border relative min-w-0 border-t px-4 py-3">
      <div className="mb-2 flex min-h-7 flex-wrap items-center justify-end gap-x-3 gap-y-1">
        {showName && (
          <p className="text-muted-foreground min-w-0 text-xs wrap-anywhere">{field.name}</p>
        )}
        <span className="text-muted-foreground mr-auto font-mono text-[10px]">{field.format}</span>
        {field.format === "markdown" && <MarkdownModeToggle mode={mode} onChange={setMode} />}
        <CopyButton text={copyableText(field.text)} className="opacity-100" />
      </div>
      {previewing ? (
        <div className="min-w-0 py-1 text-sm break-words">
          <MarkdownContent content={field.text} inertImages bareCode />
        </div>
      ) : (
        <p
          className={cn(
            "py-1 text-sm leading-relaxed break-words whitespace-pre-wrap",
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
    </div>
  );
}
