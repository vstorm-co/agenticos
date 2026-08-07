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

const PILL: Record<StatusTone, string> = {
  ok: "text-success",
  warn: "text-warning",
  err: "text-destructive",
  neutral: "text-muted-foreground",
};

/** Dot + name + status pill rows - health-style lists. */
export function StatusList({ rows, className }: { rows: StatusRow[]; className?: string }) {
  return (
    <ul className={cn("space-y-2.5", className)}>
      {rows.map((row) => (
        <li key={row.label} className="flex items-center gap-2 text-sm">
          <span className={cn("size-2 shrink-0 rounded-full", DOT[row.tone])} aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="text-foreground block truncate">{row.label}</span>
            {row.sub ? (
              <span className="text-muted-foreground block truncate text-xs">{row.sub}</span>
            ) : null}
          </span>
          <span className={cn("shrink-0 text-xs font-medium whitespace-nowrap", PILL[row.tone])}>
            {row.pill}
          </span>
        </li>
      ))}
    </ul>
  );
}
