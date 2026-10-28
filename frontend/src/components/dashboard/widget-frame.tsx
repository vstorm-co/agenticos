"use client";

import { useRef, type ReactNode } from "react";
import Link from "next/link";
import { Info } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import type { WidgetOptions } from "@/lib/dashboard/layouts";
import { SCROLL_FADE_Y, useScrollFade } from "@/components/ui/scroll-fade";
import { CARD_SURFACE } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import { WidgetOptionChips } from "./widget-option-chips";

interface WidgetFrameProps {
  title: string;
  /**
   * What this card overrides about itself. Drawn in the header as chips, and
   * that is not decoration: a card answering about ninety days while the page
   * filter says thirty, or about one agent while everything beside it counts
   * all of them, is lying unless it says so where the number is read.
   */
  options?: WidgetOptions;
  /**
   * The paragraph that used to sit in the body in muted grey. It is the answer
   * to "what am I actually looking at" - true, worth having, and read by
   * nobody once eleven cards each carry three lines of it. Behind the header's
   * info icon the card stays scannable and the explanation stays one hover
   * away.
   */
  hint?: string;
  /** Route of the page that shows the whole answer; renders the corner link. */
  seeAll?: string;
  className?: string;
  children: ReactNode;
}

/**
 * The card shell every widget renders in: title, optional explanation and
 * "see all" link, then the body.
 *
 * Uses the console's card surface and spacing, without an internal header rule.
 * Lists and charts share the shell while keeping their own content structure.
 *
 * `h-full` so a card stretched by a taller row sibling fills its cell instead
 * of leaving slack under the border.
 *
 * `overflow-hidden` is load-bearing, not tidiness: a body that cannot shrink to
 * the height its cell was given - the heatmap's twenty-four aspect-square
 * columns were the case - otherwise paints *over* this header rather than
 * being clipped by the card that holds it.
 */
export function WidgetFrame({
  title,
  hint,
  seeAll,
  options,
  className,
  children,
}: WidgetFrameProps) {
  const t = useTranslations("dashboard");
  const body = useRef<HTMLDivElement>(null);
  // The bottom edge fades while there is more below, so a list longer than its
  // cell reads as one to scroll rather than as one cut off.
  useScrollFade(body, "y");
  return (
    <Card
      // `group` so a body can answer the pointer over the whole card rather
      // than only over itself - `WidgetEmptyBody` brightens on it, which is how
      // a card that is waiting reads as waiting rather than as disabled.
      className={cn(
        CARD_SURFACE,
        "dash-widget group @container/widget flex h-full min-w-0 flex-col overflow-hidden shadow-none",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-0">
        <div className="flex min-w-0 items-center gap-1.5">
          <h3 className="text-foreground truncate text-sm font-semibold tracking-tight">{title}</h3>
          {hint ? <WidgetHint title={title} text={hint} /> : null}
          <WidgetOptionChips options={options} />
        </div>
        {seeAll ? (
          <Link
            href={seeAll}
            className="text-muted-foreground hover:text-foreground shrink-0 text-xs"
          >
            {t("seeAll")}
          </Link>
        ) : null}
      </div>
      {/* Scrolls, because the card clips. A list longer than the height its
          owner gave the card - eight service probes in a two-row cell - would
          otherwise be silently cut off at the border with nothing to say so. */}
      <div
        ref={body}
        className={cn("flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pt-4 pb-5", SCROLL_FADE_Y)}
      >
        {children}
      </div>
    </Card>
  );
}

function WidgetHint({ title, text }: { title: string; text: string }) {
  const t = useTranslations("dashboard");
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          // Named for its card. A page of eleven of these all labelled "What
          // this shows" is eleven identical stops to a screen reader, with
          // nothing saying which card each one belongs to.
          aria-label={t("whatThisShows", { title })}
          // A bare button around a `size-3.5` icon is a 14x14 target - under a
          // third of the 44px both mobile platforms ask for, once per card.
          // The hit area is an absolutely positioned `::before` rather than
          // padding: padding would have to be 15px a side to reach 44 and would
          // then push the title, and a negative margin to claw that back leaves
          // the *box* 44px, not the clickable area. The pseudo-element takes
          // pointer events for the button and occupies no layout at all -
          // 14 + 15 + 15 = 44.
          className="text-muted-foreground hover:text-foreground relative shrink-0 transition-colors before:absolute before:-inset-[15px] before:content-['']"
        >
          <Info className="size-3.5" aria-hidden />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-72 leading-relaxed">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}
