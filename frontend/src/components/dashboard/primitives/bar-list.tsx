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
 * The label and value share a row, with the track underneath. Long model
 * names then keep the same room as agent names, even in a narrow card.
 *
 * The hover is where a truncated label goes. A model id or a provider-prefixed
 * name outruns the label column on the narrowest card this list appears in, and
 * a native `title` is not reachable from a keyboard.
 */
export function BarList({ items, className }: { items: BarListItem[]; className?: string }) {
  const max = Math.max(...items.map((item) => item.value), 1);
  return (
    <div className={cn("flex min-h-0 flex-col gap-1", className)}>
      {items.map((item) => (
        <Tooltip key={item.label}>
          <TooltipTrigger asChild>
            {/* The row is the hit target, not the thin bar inside it: with
                `py-2` it clears the 24px a pointer can actually land on.
                A row with somewhere to go is a link - focusable, because it now
                does something when activated; one without stays a plain div, so
                a tab stop is never a promise of interactivity a row cannot
                keep. Nothing is gated behind the hover: the truncation is CSS,
                so the full label is in the DOM and a screen reader reads it
                whole. */}
            <Row href={item.href} label={item.label}>
              <span className="text-foreground flex min-w-0 items-center gap-2 font-medium">
                {/* 20px, the size the run table draws an agent at. A mark here
                    is sometimes a glyph and sometimes initials, and initials
                    need the room: two of them never fitted the 16px circle this
                    was, whatever type scale the widget asked for - see
                    `ui/avatar.tsx` on why asking had no effect. */}
                {item.icon ? (
                  <span className="flex size-5 shrink-0 items-center justify-center" aria-hidden>
                    {item.icon}
                  </span>
                ) : null}
                <span className="min-w-0 truncate">{item.label}</span>
              </span>
              <span
                className={cn("order-3 col-span-2 h-1.5 overflow-hidden rounded-full", TRACK_CLASS)}
              >
                <span
                  className={cn("block h-full rounded-full", MARK_CLASS)}
                  style={{ width: `${(item.value / max) * 100}%` }}
                />
              </span>
              <span className="text-muted-foreground shrink-0 text-right tabular-nums">
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
      "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 rounded-lg px-1 py-2 text-xs transition-colors" +
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
