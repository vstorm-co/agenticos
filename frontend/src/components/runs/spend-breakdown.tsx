"use client";

import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";

/**
 * One way of slicing the same spend.
 *
 * A row whose subject no longer exists - a provider from before this was
 * recorded, a key since deleted - is kept and muted rather than dropped. The
 * money was spent either way, and a breakdown that silently stops adding up to
 * the total is worse than one with an honest "not recorded" line in it.
 */
export function SpendBreakdown({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: { key: string; label: string; muted: boolean; runs: number; cost: string }[];
}) {
  const t = useTranslations("pages.runs");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {rows.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("nothingSpentYet2")}</p>
        ) : (
          rows.map((row) => (
            <div
              key={row.key}
              className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
            >
              <span className={row.muted ? "text-muted-foreground italic" : "font-medium"}>
                {row.label}
              </span>
              <span className="text-muted-foreground ml-auto text-xs">
                {t("runCount", { count: row.runs })}
              </span>
              <span className="font-mono">${Number(row.cost).toFixed(4)}</span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
