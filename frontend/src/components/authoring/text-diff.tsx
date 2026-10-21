"use client";

import { useMemo } from "react";

import { diffLines } from "@/lib/diff";
import { cn } from "@/lib/utils";

/**
 * A proposed change to a passage, line by line in the idiom of the History tab's
 * spec diff: the passage's surroundings for context, the removed lines and the
 * added ones.
 */
export function TextDiff({
  before,
  after,
  context = "",
  trailing = "",
}: {
  before: string;
  after: string;
  /** Text before the passage, shown unchanged. */
  context?: string;
  /** Text after the passage, shown unchanged. */
  trailing?: string;
}) {
  const lines = useMemo(
    () => diffLines(`${context}${before}${trailing}`, `${context}${after}${trailing}`),
    [before, after, context, trailing],
  );
  return (
    <div className="overflow-auto rounded-md border">
      <table className="w-full border-collapse font-mono text-xs leading-5">
        <tbody>
          {lines.map((line, index) => (
            <tr
              key={`${line.kind}-${index}`}
              className={cn(
                line.kind === "same" && "text-muted-foreground",
                line.kind === "added" && "bg-emerald-500/10",
                line.kind === "removed" && "bg-destructive/10",
              )}
            >
              <td className="text-muted-foreground w-6 px-2 py-0.5 text-center select-none">
                {/* i18n-exempt: diff gutter glyphs, the SpecDiff convention */}
                {line.kind === "added" ? "+" : line.kind === "removed" ? "−" : ""}
              </td>
              <td className="w-full py-0.5 pr-2 whitespace-pre-wrap">{line.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
