"use client";

import type { LucideIcon } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

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
  contentClassName,
  children,
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
  contentClassName?: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">{title}</CardTitle>
          <CardDescription className="text-xs">
            {counted === null ? <Skeleton className="h-3 w-24" /> : counted}
          </CardDescription>
        </div>
        {controls}
      </CardHeader>
      <CardContent className={cn("p-5", contentClassName)}>{children}</CardContent>
    </Card>
  );
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
        "border-border flex flex-wrap items-center gap-2 border-b px-5 py-3",
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
      <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
        <Icon className="h-5 w-5" />
      </div>
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
