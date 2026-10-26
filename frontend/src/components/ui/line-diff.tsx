"use client";

import { useMemo } from "react";

import { collapseUnchanged, diffLines, diffStat, MAX_DIFF_LINES } from "@/lib/diff";
import { cn } from "@/lib/utils";

interface LineDiffProps {
  before: string;
  after: string;
  /** Shown when the two texts are the same. */
  identicalLabel: string;
  /** The gap row standing in for a long unchanged stretch. */
  unchangedLabel: (count: number) => string;
  /** Shown instead of a table when either text is past `MAX_DIFF_LINES`. */
  tooLongLabel: string;
}

/**
 * Two texts as a unified diff: a `+n −m` summary over a table of changed lines
 * with their context, long unchanged stretches folded into a gap row.
 *
 * Lines render as text, never as markup, so a diff of untrusted text is safe.
 */
export function LineDiff({
  before,
  after,
  identicalLabel,
  unchangedLabel,
  tooLongLabel,
}: LineDiffProps) {
  // `diffLines` answers a text past the limit with one removed and one added row
  // rather than a signal, so the limit is checked here, before the work.
  const tooLong =
    before.split("\n").length > MAX_DIFF_LINES || after.split("\n").length > MAX_DIFF_LINES;
  const lines = useMemo(() => (tooLong ? [] : diffLines(before, after)), [tooLong, before, after]);
  const stat = diffStat(lines);
  const rows = useMemo(() => collapseUnchanged(lines), [lines]);

  if (tooLong) {
    return <p className="text-muted-foreground text-sm">{tooLongLabel}</p>;
  }
  if (stat.added === 0 && stat.removed === 0) {
    return <p className="text-muted-foreground text-sm">{identicalLabel}</p>;
  }

  return (
    <div className="space-y-2">
      <p className="font-mono text-xs">
        <span className="text-emerald-600 dark:text-emerald-400">+{stat.added}</span>{" "}
        <span className="text-destructive">−{stat.removed}</span>
      </p>
      {/* No line-number gutters: they numbered a serialization nobody has a
          copy of, and two columns of them out-inked the diff itself. */}
      <div className="max-h-96 overflow-auto rounded-md border">
        <table className="w-full border-collapse font-mono text-xs leading-5">
          <tbody>
            {rows.map((row, index) =>
              row.kind === "gap" ? (
                <tr key={`gap-${index}`} className="bg-muted/40">
                  <td colSpan={2} className="text-muted-foreground px-3 py-1 text-center">
                    {unchangedLabel(row.hidden)}
                  </td>
                </tr>
              ) : (
                <tr
                  key={`${row.kind}-${row.before ?? ""}-${row.after ?? ""}-${index}`}
                  className={cn(
                    row.kind === "same" && "text-muted-foreground",
                    row.kind === "added" && "bg-emerald-500/10",
                    row.kind === "removed" && "bg-destructive/10",
                  )}
                >
                  <td className="text-muted-foreground w-6 px-2 py-0.5 text-center select-none">
                    {row.kind === "added" ? "+" : row.kind === "removed" ? "−" : ""}
                  </td>
                  <td className="w-full py-0.5 pr-2 whitespace-pre-wrap">{row.text}</td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
