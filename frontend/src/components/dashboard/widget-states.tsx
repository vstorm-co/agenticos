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

export function WidgetSkeleton({
  rows = 3,
  variant = "list",
  className,
  columns = 4,
}: {
  rows?: number;
  columns?: 3 | 4;
  variant?: "list" | "metrics" | "chart" | "gallery" | "bars" | "table" | "services";
  className?: string;
}) {
  const t = useTranslations("dashboard.states");
  return (
    <div
      role="status"
      aria-label={t("loading")}
      className={cn(
        "flex min-h-0 flex-1 animate-pulse flex-col gap-4 py-1 motion-reduce:animate-none",
        className,
      )}
    >
      {variant === "metrics" ? (
        <div
          aria-hidden
          className={cn(
            "grid gap-5",
            columns === 3 ? "grid-cols-3" : "grid-cols-2 @[40rem]/widget:grid-cols-4",
          )}
        >
          {Array.from({ length: columns }, (_, index) => (
            <div key={index} className="space-y-3">
              <div className="bg-muted h-3 w-16 rounded" />
              <div className="bg-muted h-7 w-20 max-w-full rounded" />
              <div className="bg-muted h-3 w-12 rounded" />
            </div>
          ))}
        </div>
      ) : variant === "bars" ? (
        <div aria-hidden className="space-y-5">
          {Array.from({ length: rows }, (_, index) => (
            <div key={index} className="space-y-2">
              <div className="flex items-center justify-between gap-4">
                <div className="bg-muted h-3 w-2/5 rounded" />
                <div className="bg-muted h-3 w-8 rounded" />
              </div>
              <div
                className="bg-muted h-1.5 rounded-full"
                style={{ width: `${90 - index * 15}%` }}
              />
            </div>
          ))}
        </div>
      ) : variant === "services" ? (
        <div aria-hidden className="grid grid-cols-[repeat(auto-fit,minmax(4.25rem,1fr))] gap-4">
          {Array.from({ length: 5 }, (_, index) => (
            <div key={index} className="flex flex-col items-center gap-2">
              <div className="bg-muted size-9 rounded-xl" />
              <div className="bg-muted h-3 w-14 rounded" />
              <div className="bg-muted h-2.5 w-10 rounded" />
            </div>
          ))}
        </div>
      ) : variant === "table" ? (
        <div aria-hidden className="space-y-4">
          {Array.from({ length: rows + 1 }, (_, index) => (
            <div
              key={index}
              className={cn(
                "grid items-center gap-4",
                columns === 3 ? "grid-cols-[2fr_1fr_1fr]" : "grid-cols-[2fr_1fr_1fr_1fr]",
              )}
            >
              {Array.from({ length: columns }, (_, cell) => (
                <div key={cell} className={cn("bg-muted h-3 rounded", index === 0 && "w-3/4")} />
              ))}
            </div>
          ))}
        </div>
      ) : variant === "gallery" ? (
        <div aria-hidden className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {Array.from({ length: rows }, (_, index) => (
            <div key={index} className="space-y-2">
              <div className="bg-muted h-3 w-3/4 rounded" />
              <div className="bg-muted aspect-[4/3] rounded-lg" />
            </div>
          ))}
        </div>
      ) : variant === "chart" ? (
        <div aria-hidden className="flex min-h-24 flex-1 flex-col gap-5">
          <div className="bg-muted h-7 w-20 shrink-0 rounded" />
          <div className="border-foreground/8 flex min-h-16 flex-1 items-end gap-2 border-b pb-2">
            {[35, 55, 45, 70, 50, 80, 65, 90].map((height, index) => (
              <div
                key={index}
                className="bg-muted flex-1 rounded-t"
                style={{ height: `${height}%` }}
              />
            ))}
          </div>
        </div>
      ) : (
        <div aria-hidden className="space-y-4">
          {Array.from({ length: rows }, (_, index) => (
            <div key={index} className="flex items-center gap-3">
              <div className="bg-muted size-8 shrink-0 rounded-lg" />
              <div className="min-w-0 flex-1 space-y-2">
                <div className="bg-muted h-3 rounded" style={{ width: `${75 - index * 12}%` }} />
                <div className="bg-muted h-2.5 w-2/5 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}
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
    <div className="flex flex-1 items-center justify-center gap-3 py-3">
      <span
        aria-hidden
        className="bg-foreground/[0.04] text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-xl"
      >
        <Icon className="size-4" />
      </span>
      <div className="max-w-64 min-w-0 space-y-1 text-left">
        <p className="text-foreground text-sm font-medium">{title}</p>
        {description ? (
          <p className="text-muted-foreground text-xs leading-relaxed">{description}</p>
        ) : null}
      </div>
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
