"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type StatusTone = "ok" | "warn" | "err" | "neutral";

export interface StatusRow {
  /** What tells two rows apart when their labels match - two bots both named "test". */
  id?: string;
  label: string;
  sub?: string;
  pill: string;
  tone: StatusTone;
  /**
   * The row's own mark, drawn in place of the tone dot - a channel's brand
   * glyph, a server's icon. The tone does not disappear with it: it moves to
   * the mark's own colour, and the status word remains explicit.
   */
  icon?: ReactNode;
}

const DOT: Record<StatusTone, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  err: "bg-destructive",
  neutral: "bg-muted-foreground",
};

/** The same tones as {@link DOT}, for a row whose mark is a glyph, not a dot. */
const MARK: Record<StatusTone, string> = {
  ok: "text-foreground",
  warn: "text-warning",
  err: "text-destructive",
  neutral: "text-muted-foreground",
};

/** Quiet rows with an optional service mark and an explicitly named status. */
export function StatusList({ rows, className }: { rows: StatusRow[]; className?: string }) {
  return (
    <ul className={cn("space-y-1", className)}>
      {rows.map((row) => (
        <li key={row.id ?? row.label} className="flex min-h-11 items-center gap-3 py-2 text-sm">
          {row.icon ? (
            <span
              className={cn(
                "bg-foreground/[0.04] flex size-8 shrink-0 items-center justify-center rounded-lg",
                MARK[row.tone],
              )}
              aria-hidden
            >
              {row.icon}
            </span>
          ) : null}
          <span className="min-w-0 flex-1">
            <span className="text-foreground block truncate font-medium">{row.label}</span>
            {row.sub ? (
              <span className="text-muted-foreground block truncate text-xs">{row.sub}</span>
            ) : null}
          </span>
          <span className="text-muted-foreground inline-flex max-w-[45%] shrink-0 items-center gap-1.5 text-xs">
            <span className={cn("size-1.5 shrink-0 rounded-full", DOT[row.tone])} aria-hidden />
            <span className="truncate">{row.pill}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
