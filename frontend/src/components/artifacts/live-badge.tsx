"use client";

import { useTranslations } from "next-intl";

import { StatusDot } from "@/components/agents/status-badge";
import { Badge } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * How a live page's data stands, as its badge shows it. `steady` is a page
 * whose data this surface does not read - a card, the dashboard - or one whose
 * last read said nothing about its sources. A viewer served no source at all
 * gets no badge: nothing on the page is live for them.
 */
export type LiveHealth = "flowing" | "partial" | "steady";

const DOT: Record<LiveHealth, string> = {
  flowing: "bg-success animate-pulse",
  partial: "bg-warning",
  steady: "bg-success",
};

/**
 * "Live" beside a page's title, as the console marks a status: a dot beside quiet
 * text. The dot pulses only while the page's data is arriving; what is wrong with
 * it, when something is, is said in words under the viewer's strip.
 */
export function LiveBadge({
  health = "steady",
  className,
}: {
  health?: LiveHealth;
  className?: string;
}) {
  const t = useTranslations("artifacts");
  return (
    <Badge
      variant="outline"
      data-health={health}
      className={cn("text-muted-foreground", className)}
    >
      <StatusDot className={DOT[health]} />
      {t("liveBadge")}
    </Badge>
  );
}
