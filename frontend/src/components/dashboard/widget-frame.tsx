"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Info } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import { cn } from "@/lib/utils";

interface WidgetFrameProps {
  title: string;
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
 */
export function WidgetFrame({ title, hint, seeAll, className, children }: WidgetFrameProps) {
  const t = useTranslations("dashboard");
  return (
    <Card className={cn("flex h-full min-w-0 flex-col", className)}>
      <div className="border-border flex items-center justify-between gap-2 border-b px-5 py-3">
        <div className="flex min-w-0 items-center gap-1.5">
          <h3 className="text-foreground truncate text-sm font-semibold tracking-tight">{title}</h3>
          {hint ? <WidgetHint title={title} text={hint} /> : null}
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
      <div className="flex min-h-0 flex-1 flex-col p-5">{children}</div>
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
          className="text-muted-foreground/50 hover:text-foreground shrink-0 transition-colors"
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
