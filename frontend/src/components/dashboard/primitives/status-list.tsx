"use client";

import { cn } from "@/lib/utils";

export type StatusTone = "ok" | "warn" | "err" | "neutral";

export interface StatusRow {
  label: string;
  sub?: string;
  pill: string;
  tone: StatusTone;
}

const DOT: Record<StatusTone, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  err: "bg-destructive",
  neutral: "bg-muted-foreground",
};

/**
 * The pill is a tinted chip, not coloured text.
 *
 * Coloured text on a card is a word shouted at whatever weight the tone
 * happens to have - four green "ok"s down a healthy card were the loudest ink
 * on it, for the least news on the page. A chip puts the tone in a 12% wash and
 * leaves the word at text weight, so a red one is the only thing that carries.
 */
const PILL: Record<StatusTone, string> = {
  ok: "bg-success/12 text-success",
  warn: "bg-warning/12 text-warning",
  err: "bg-destructive/12 text-destructive",
  neutral: "bg-muted text-muted-foreground",
};

/** Dot + name + status pill rows - health-style lists. */
export function StatusList({ rows, className }: { rows: StatusRow[]; className?: string }) {
  return (
    <ul className={cn("space-y-1", className)}>
      {rows.map((row) => (
        <li key={row.label} className="flex items-center gap-2.5 py-1 text-sm">
          <span className={cn("size-1.5 shrink-0 rounded-full", DOT[row.tone])} aria-hidden />
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
