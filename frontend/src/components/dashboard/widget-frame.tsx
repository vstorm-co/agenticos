"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Info } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import type { WidgetOptions } from "@/lib/dashboard/layouts";
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
 * Built on `Card` rather than on its own border and radius, so a widget is the
 * same object as a `ListCard` on Skills or a figure on Activity - same corner,
 * same elevation, same divider under the heading. It carried `rounded-xl` and
 * no shadow while every other surface in the product carried `rounded-2xl` and
 * one, which reads as a different product on the one page that shows all of
 * them at once.
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
  return (
    <Card
      className={cn(
        CARD_SURFACE,
        "flex h-full min-w-0 flex-col overflow-hidden shadow-none",
        className,
      )}
    >
      {/* The rule under the heading is the card's own edge tone, not the page's
          border: on a translucent surface `border-border` is a hard grey line
          drawn across frosted glass. */}
      <div className="border-foreground/8 flex items-center justify-between gap-2 border-b px-5 py-3.5">
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
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-5">{children}</div>
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
          className="text-muted-foreground/50 hover:text-foreground relative shrink-0 transition-colors before:absolute before:-inset-[15px] before:content-['']"
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
