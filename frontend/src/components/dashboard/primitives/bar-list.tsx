"use client";

import { cn } from "@/lib/utils";

export interface BarListItem {
  label: string;
  value: number;
  /** What to print beside the track; defaults to the value itself. */
  display?: string;
}

/**
 * Label / proportional track / value rows. Plain divs, no chart library:
 * the values are printed as text by design, so colour is never the only
 * channel and a screen reader gets the same numbers a sighted reader does.
 */
export function BarList({ items, className }: { items: BarListItem[]; className?: string }) {
  const max = Math.max(...items.map((item) => item.value), 1);
  return (
    <div className={cn("space-y-2", className)}>
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground w-28 shrink-0 truncate" title={item.label}>
            {item.label}
          </span>
          <span className="bg-foreground/5 h-2 flex-1 overflow-hidden rounded-full">
            <span
              className="bg-chart block h-full rounded-full"
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </span>
          <span className="text-foreground w-14 shrink-0 text-right font-medium tabular-nums">
            {item.display ?? item.value.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}
