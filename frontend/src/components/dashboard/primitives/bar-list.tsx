"use client";

import { forwardRef, type ReactNode } from "react";
import Link from "next/link";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import { MARK_CLASS, TRACK_CLASS } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";

export interface BarListItem {
  label: string;
  value: number;
  /** What to print beside the track; defaults to the value itself. */
  display?: string;
  /**
   * The row's own mark - an agent's avatar, a surface's brand glyph. Decorative:
   * the label beside it carries the name, so a mark is never the only thing
   * saying which row this is. The same faces the run table draws, from the same
   * modules, so one agent does not wear two.
   */
  icon?: ReactNode;
  /**
   * Where this row's own rows live - Activity, narrowed to what the row names.
   * A card that says "Mattermost 31" and cannot offer those 31 is a dead end,
   * which is what every slice on this page was until #768 put the run history's
   * filters in the URL. Absent on a row with nothing to point at.
   */
  href?: string;
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
    // Centred in whatever height the card has. A card's height is its owner's
    // choice and a list of three surfaces does not grow to meet it, so the
    // alternative is three rows at the top and a hand's height of nothing
    // under them - which is what most of the dashboard looked like.
    <div className={cn("flex min-h-0 flex-1 flex-col justify-center gap-0.5", className)}>
      {items.map((item) => (
        <Tooltip key={item.label}>
          <TooltipTrigger asChild>
            {/* The row is the hit target, not the 8px bar inside it: with
                `py-1.5` it clears the 24px a pointer can actually land on.
                A row with somewhere to go is a link - focusable, because it now
                does something when activated; one without stays a plain div, so
                a tab stop is never a promise of interactivity a row cannot
                keep. Nothing is gated behind the hover: the truncation is CSS,
                so the full label is in the DOM and a screen reader reads it
                whole. */}
            <Row href={item.href} label={item.label}>
              <span className="text-muted-foreground flex w-36 shrink-0 items-center gap-1.5">
                {item.icon ? (
                  <span className="flex size-4 shrink-0 items-center justify-center" aria-hidden>
                    {item.icon}
                  </span>
                ) : null}
                <span className="min-w-0 truncate">{item.label}</span>
              </span>
              <span className={cn("h-2 flex-1 overflow-hidden rounded-r-sm", TRACK_CLASS)}>
                <span
                  className={cn("block h-full rounded-r-sm", MARK_CLASS)}
                  style={{ width: `${(item.value / max) * 100}%` }}
                />
              </span>
              <span className="text-foreground w-14 shrink-0 text-right font-medium tabular-nums">
                {item.display ?? item.value.toLocaleString()}
              </span>
            </Row>
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

/**
 * The row itself: a link when it has somewhere to go, a plain box otherwise.
 *
 * `forwardRef` because Radix's `asChild` hands the tooltip trigger's ref to
 * whatever this returns, and a function component that swallows it leaves the
 * tooltip anchored to nothing.
 */
const Row = forwardRef<HTMLElement, { href?: string; label: string; children: ReactNode }>(
  function Row({ href, label, children }, ref) {
    const className =
      "flex items-center gap-2 rounded-md py-1.5 text-xs transition-colors" +
      (href
        ? " hover:bg-muted/60 focus-visible:ring-ring focus-visible:ring-2 outline-none"
        : " cursor-default");
    if (!href) {
      return (
        <div ref={ref as React.Ref<HTMLDivElement>} className={className}>
          {children}
        </div>
      );
    }
    return (
      <Link
        ref={ref as React.Ref<HTMLAnchorElement>}
        href={href}
        aria-label={label}
        className={className}
      >
        {children}
      </Link>
    );
  },
);
