"use client";

import { Inbox, TriangleAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * The three in-card states, compact on purpose: the page-level EmptyState and
 * ErrorState render their own bordered cards, and nesting those inside a
 * widget frame double-borders. Every widget fails alone - the error body says
 * so, and its Retry refetches only that widget's query.
 */

export function WidgetSkeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  const t = useTranslations("dashboard.states");
  return (
    <div
      role="status"
      aria-label={t("loading")}
      className={cn("animate-pulse space-y-3 py-1", className)}
    >
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="bg-muted h-4 rounded"
          style={{ width: `${100 - index * 18}%` }}
        />
      ))}
    </div>
  );
}

export function WidgetEmptyBody({
  title,
  description,
  icon: Icon = Inbox,
}: {
  title: string;
  description?: string;
  /**
   * The subject this card is waiting for - a plug for MCP, a bot for channels.
   * Defaults to the tray, which is the honest glyph for "nothing has arrived"
   * but says the same thing on every card that shows it.
   */
  icon?: LucideIcon;
}) {
  return (
    // Dimmed, and it brightens under the pointer. On a young deployment
    // fourteen of these are on one page - approvals, channels, routines,
    // sandboxes, ratings, sync, notifications - each one a full-height card
    // reporting that nothing has happened, at the same contrast as the cards
    // carrying real numbers. At equal weight the page reads as mostly absence
    // and the eye has to work out which cards are worth stopping at.
    //
    // So a waiting card recedes: enough contrast to be read when looked at,
    // little enough to be skipped when not. The hover is what keeps that from
    // reading as *disabled* - a card that answers the pointer is one that will
    // hold something later, and the header above it stays at full strength
    // either way, so the card never stops saying what it is.
    //
    // `motion-safe` on the transition only: somebody who turned motion down
    // still gets the hover, without the fade.
    <div className="flex flex-1 flex-col items-center justify-center gap-2 py-6 text-center opacity-60 transition-opacity duration-200 group-hover:opacity-100 motion-reduce:transition-none">
      {/* A dashed plate, not a bare glyph: it reads as a slot waiting to be
          filled rather than as a status icon reporting a fault. */}
      <span
        aria-hidden
        className="border-foreground/15 text-muted-foreground/70 flex size-9 items-center justify-center rounded-xl border border-dashed"
      >
        <Icon className="size-4" />
      </span>
      <p className="text-foreground/80 text-sm font-medium">{title}</p>
      {description ? (
        <p className="text-muted-foreground max-w-60 text-xs leading-relaxed">{description}</p>
      ) : null}
    </div>
  );
}

export function WidgetErrorBody({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations("dashboard.errors");
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 py-6 text-center">
      <TriangleAlert className="text-destructive size-5" aria-hidden />
      <p className="text-foreground text-sm font-medium">{t("title")}</p>
      <p className="text-muted-foreground max-w-60 text-xs">{t("description")}</p>
      <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
        {t("retry")}
      </Button>
    </div>
  );
}
