"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import { CopyButton } from "./copy-button";
import { cn } from "@/lib/utils";

interface CollapsibleBlockProps {
  /**
   * What the header calls the contents - a language, or what the output is.
   *
   * `null` is a block with nothing worth heading, and it loses the header bar rather
   * than showing an empty one. A collapsible block keeps it whatever the label,
   * because the header is the only thing left of it once it is closed.
   */
  label: string | null;
  /** What the copy button takes. Nothing to copy is no button. */
  copyText?: string;
  /**
   * Whether the block is open - and, by being set at all, that it can be closed.
   *
   * `undefined` is a block that is always open and has no chevron: a fenced block in
   * an answer, which is the whole of what its message had to say. A boolean makes the
   * block collapsible, and is a *starting* state rather than a binding - it is applied
   * when it changes and a click wins over it until it changes again.
   *
   * That distinction is the point of the component. A `run_python` step shows its code
   * while it runs, closes it when the output arrives, and still respects somebody who
   * re-opened it half a second later: the streaming deltas that re-render this subtree
   * pass the same value every time, so they leave the click alone.
   */
  open?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * A body of text under a header that names it - code, output, a command's stdout.
 *
 * A tool call is usually a pair: what was sent and what came back. Both are text in a
 * box, both want a copy button, and only one of them is worth reading at a time, which
 * is what makes the box collapsible rather than the step it sits in.
 */
export function CollapsibleBlock({
  label,
  copyText,
  open,
  className,
  children,
}: CollapsibleBlockProps) {
  const collapsible = open !== undefined;
  const [expanded, setExpanded] = useState(open ?? true);
  // Written during render, so a block whose owner just decided it should close is
  // never shown open for a frame first. `seen` is what makes the prop a starting
  // state: only a *change* in it overrides what somebody clicked.
  const [seen, setSeen] = useState(open);
  if (seen !== open) {
    setSeen(open);
    setExpanded(open !== false);
  }

  return (
    <div
      className={cn("group border-border bg-muted overflow-hidden rounded-xl border", className)}
    >
      {(label !== null || collapsible) && (
        <div className="border-foreground/8 text-foreground/55 flex items-center justify-between border-b px-3 py-1.5 font-mono text-[10px] tracking-wider uppercase">
          {collapsible ? (
            <button
              type="button"
              onClick={() => setExpanded((previous) => !previous)}
              aria-expanded={expanded}
              className="hover:text-foreground flex min-w-0 items-center gap-1.5"
            >
              <ChevronDown
                className={cn("h-3 w-3 shrink-0 transition-transform", !expanded && "-rotate-90")}
                aria-hidden
              />
              <span className="truncate">{label}</span>
            </button>
          ) : (
            <span className="truncate">{label}</span>
          )}
          {/* Never hidden until hover: on a code block this is the most-used control
              there is, and a control nobody can see is one nobody uses. */}
          {copyText !== undefined && copyText !== "" && (
            <CopyButton text={copyText} className="opacity-100 transition-opacity" />
          )}
        </div>
      )}
      {expanded && children}
    </div>
  );
}
