"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type StatusTone = "ok" | "warn" | "err" | "neutral";

export interface StatusRow {
  label: string;
  sub?: string;
  pill: string;
  tone: StatusTone;
  /**
   * The row's own mark, drawn in place of the tone dot - a channel's brand
   * glyph, a server's icon. The tone does not disappear with it: it moves to
   * the mark's own colour, and the pill still spells the status out.
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

/**
 * The pill is a tinted chip, not coloured text.
 *
 * Coloured text on a card is a word shouted at whatever weight the tone
 * happens to have - four green "ok"s down a healthy card were the loudest ink
 * on it, for the least news on the page. A chip puts the tone in a wash and an
 * edge and leaves the word in text colour - red words on a red wash measured
 * under 3:1 - so the hue says which, and the word stays readable.
 */
const PILL: Record<StatusTone, string> = {
  ok: "border border-success/30 bg-success/10 text-foreground",
  warn: "border border-warning/35 bg-warning/10 text-foreground",
  err: "border border-destructive/35 bg-destructive/10 text-foreground",
  neutral: "border border-border bg-muted text-muted-foreground",
};

/** Dot + name + status pill rows - health-style lists. */
export function StatusList({ rows, className }: { rows: StatusRow[]; className?: string }) {
  return (
    <ul className={cn("space-y-1", className)}>
      {rows.map((row) => (
        <li key={row.label} className="flex items-center gap-2.5 py-1 text-sm">
          {row.icon ? (
            <span
              className={cn("flex size-4 shrink-0 items-center justify-center", MARK[row.tone])}
              aria-hidden
            >
              {row.icon}
            </span>
          ) : (
            <span className={cn("size-1.5 shrink-0 rounded-full", DOT[row.tone])} aria-hidden />
          )}
          <span className="min-w-0 flex-1">
            <span className="text-foreground block truncate">{row.label}</span>
            {row.sub ? (
              <span className="text-muted-foreground block truncate text-xs">{row.sub}</span>
            ) : null}
          </span>
          <span
            className={cn(
              "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
              PILL[row.tone],
            )}
          >
            {row.pill}
          </span>
        </li>
      ))}
    </ul>
  );
}
