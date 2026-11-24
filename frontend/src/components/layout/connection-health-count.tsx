"use client";

import { useTranslations } from "next-intl";

import { useConnectionHealth } from "@/hooks/use-connection-health";

/** How many connections need attention: a number in the column, a dot on the rail. */
export function ConnectionHealthCount({ collapsed }: { collapsed: boolean }) {
  const t = useTranslations("nav");
  const { total } = useConnectionHealth();
  if (total === 0) return null;
  // Destructive, not muted like the inbox count: this is not something
  // waiting, it is something broken, and the column should say so at a glance.
  const label = t("connectionHealthCount", { count: total });
  return collapsed ? (
    <span
      className="bg-destructive absolute top-1 right-1 h-1.5 w-1.5 rounded-full"
      aria-label={label}
    />
  ) : (
    <span
      className="text-destructive ml-auto px-1 text-xs font-medium tabular-nums"
      aria-label={label}
    >
      {total}
    </span>
  );
}
