"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import { MARK_CLASS, TRACK_CLASS } from "@/lib/dashboard/system";
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
 *
 * Every bar is one hue. These are nominal categories - surfaces, models,
 * agents - and colouring each differently would spend the identity channel
 * re-encoding what bar length already says.
 *
 * The bar is square where it starts and rounded where it ends, so the baseline
 * reads as a baseline; a pill floats. The track behind it is the fill's own hue
 * several steps lighter rather than a neutral alpha, so a row reads as one
 * quantity against its ceiling rather than as a mark laid on grey.
 *
 * The hover is where a truncated label goes. A model id or a provider-prefixed
 * name outruns the label column on the narrowest card this list appears in, and
 * a native `title` is not reachable from a keyboard.
 */
export function BarList({ items, className }: { items: BarListItem[]; className?: string }) {
  const max = Math.max(...items.map((item) => item.value), 1);
  return (
    <div className={cn("space-y-1", className)}>
      {items.map((item) => (
        <Tooltip key={item.label}>
          <TooltipTrigger asChild>
            {/* The row is the hit target, not the 8px bar inside it: with
                `py-1.5` it clears the 24px a pointer can actually land on.
                Deliberately not focusable - the row does nothing when
                activated, and a tab stop that only reveals a tooltip is a
                promise of interactivity the row cannot keep. Nothing is gated
                behind the hover: the truncation is CSS, so the full label is in
                the DOM and a screen reader reads it whole. */}
            <div className="flex cursor-default items-center gap-2 rounded-md py-1.5 text-xs">
              <span className="text-muted-foreground w-36 shrink-0 truncate">{item.label}</span>
              <span className={cn("h-2 flex-1 overflow-hidden rounded-r-sm", TRACK_CLASS)}>
                <span
                  className={cn("block h-full rounded-r-sm", MARK_CLASS)}
                  style={{ width: `${(item.value / max) * 100}%` }}
                />
              </span>
              <span className="text-foreground w-14 shrink-0 text-right font-medium tabular-nums">
                {item.display ?? item.value.toLocaleString()}
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent side="top" className="flex items-center gap-2">
            <span>{item.label}</span>
            <span className="font-medium">{item.display ?? item.value.toLocaleString()}</span>
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}
