"use client";

import type { LucideIcon } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

import { SectionGlyph } from "@/components/states/section-glyph";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The resource-list page's frame, drawn whether or not there is anything in
 * it - one card instead of the five per-page copies it replaces (#282).
 *
 * Same header, same border, in every state: what changes is what is inside.
 * A card that only appears once rows exist reads as the panel disappearing
 * the moment you use it.
 */
export function ListCard({
  title,
  counted,
  controls,
  namedByPage = false,
  empty = false,
  contentClassName,
  headerTour,
  children,
  ...rest
}: {
  title: string;
  /**
   * The count line, already formatted through the caller's ICU plural
   * ("40 skills", "1 key stored") - the noun declines with the number, so no
   * parameter can carry it (#362). `null` while the request is in flight
   * draws a skeleton: rendering "0 skills" before the answer would state
   * something about the organization nothing has said yet.
   */
  counted: string | null;
  /** The header's right side - a search box, a view toggle. */
  controls?: ReactNode;
  /**
   * The card is the page's own list, under a page header that already names
   * it. "Skills" over "Skills · 11 skills" said the same word twice before the
   * first row, so the header becomes a toolbar - the count, then the controls -
   * and the title is kept for a screen reader only.
   */
  namedByPage?: boolean;
  /**
   * Under `namedByPage`: there is nothing yet, so there is nothing to count or
   * search, and a strip reading "0 skills" above "No skills yet" said it twice.
   * The toolbar is dropped and the empty state stands alone.
   */
  empty?: boolean;
  contentClassName?: string;
  /**
   * A walkthrough anchor (`data-tour`) on the header alone. A stop that describes
   * the card spotlights this rather than the card, whose body is the whole list —
   * lighting a catalog taller than the screen highlights nothing.
   */
  headerTour?: string;
  children: ReactNode;
} & HTMLAttributes<HTMLDivElement>) {
  if (namedByPage) {
    return (
      <Card {...rest}>
        <CardHeader
          data-tour={headerTour}
          className={cn(
            "flex-col gap-3 space-y-0 border-b px-4 py-3 sm:min-h-14 sm:flex-row sm:items-center sm:justify-between sm:px-5",
            empty && "sr-only",
          )}
        >
          <CardTitle className="sr-only">{title}</CardTitle>
          <div className="text-muted-foreground shrink-0 text-sm">
            {counted === null ? <Skeleton className="h-4 w-24" /> : counted}
          </div>
          {controls}
        </CardHeader>
        <CardContent className={contentPadding(contentClassName)}>{children}</CardContent>
      </Card>
    );
  }
  return (
    <Card {...rest}>
      {/* A column on a phone: beside a search box and three filters the title
          was squeezed to "Catalo", and it is the one thing in the header that
          says what the card is. */}
      <CardHeader
        data-tour={headerTour}
        className="flex-col gap-3 space-y-0 border-b px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5"
      >
        <div className="shrink-0 space-y-1">
          <CardTitle className="text-sm">{title}</CardTitle>
          <CardDescription className="text-xs">
            {counted === null ? <Skeleton className="h-3 w-24" /> : counted}
          </CardDescription>
        </div>
        {controls}
      </CardHeader>
      <CardContent className={contentPadding(contentClassName)}>{children}</CardContent>
    </Card>
  );
}

/**
 * The content's classes: tighter on a phone, where a card of cards spent a third
 * of the width on two paddings - unless the caller sets padding of its own.
 *
 * Not `cn("p-3 sm:p-5", own)`: merging drops `p-3` for the caller's `p-0` but
 * keeps `sm:p-5`, so a flush table regained a 20px inset from the small
 * breakpoint up.
 */
function contentPadding(own: string | undefined): string {
  // A caller that sets padding of its own keeps the plain default under it -
  // "pb-6" still wants the other three sides - and merges cleanly with it.
  return own !== undefined && /(^|\s)p[xytrbl]?-/.test(own)
    ? cn("p-5", own)
    : cn("p-3 sm:p-5", own);
}

/**
 * The filter strip at the top of a `ListCard`'s flush (`p-0`) content -
 * selects, facet pills, canned views, whatever narrows the table below it.
 *
 * Inside the card on purpose: a control that narrows a table belongs in the
 * container the table lives in, and half the pages had grown their own row
 * floating above the card - each with its own gap, its own alignment, and no
 * divider. One strip, one set of classes.
 */
export function ListCardControlsRow({
  className,
  children,
  ...props
}: {
  className?: string;
  children: ReactNode;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        // Wrapped on every screen: swiped sideways on a phone, the last
        // filter sat past the edge cut mid-word, and nobody found it.
        "border-border flex flex-wrap items-center gap-2 border-b px-4 py-3 sm:px-5",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

/**
 * The foot strip of a `ListCard`'s flush content - a pager, a load-more, a
 * "showing X of Y" line. The counterpart of `ListCardControlsRow`.
 */
export function ListCardFootRow({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn("border-border border-t px-5 py-3", className)}>{children}</div>;
}

/**
 * The empty state for content *inside* a `ListCard`.
 *
 * Not `EmptyState`: that component draws its own bordered box, and inside a
 * card it would frame one message twice - the reason four pages each carried
 * this block inline before it was shared.
 */
export function ListCardEmpty({
  icon: Icon,
  title,
  description,
  cta,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  cta?: { label: ReactNode; onClick: () => void };
}) {
  return (
    <div className="px-6 py-16 text-center">
      <SectionGlyph icon={Icon} className="mx-auto" />
      <p className="text-foreground mt-4 text-sm font-medium">{title}</p>
      {description && (
        <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">{description}</p>
      )}
      {cta && (
        <Button variant="outline" size="sm" className="mt-5" onClick={cta.onClick}>
          {cta.label}
        </Button>
      )}
    </div>
  );
}
