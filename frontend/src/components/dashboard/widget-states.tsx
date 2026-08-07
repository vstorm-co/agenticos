"use client";

import { Inbox, TriangleAlert } from "lucide-react";
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
          className="bg-foreground/5 h-4 rounded"
          style={{ width: `${100 - index * 18}%` }}
        />
      ))}
    </div>
  );
}

export function WidgetEmptyBody({ title, description }: { title: string; description?: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 py-6 text-center">
      <Inbox className="text-muted-foreground/60 size-5" aria-hidden />
      <p className="text-foreground text-sm font-medium">{title}</p>
      {description ? <p className="text-muted-foreground max-w-60 text-xs">{description}</p> : null}
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
