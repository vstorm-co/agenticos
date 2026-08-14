"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";

/**
 * One way of slicing the same spend.
 *
 * A row whose subject no longer exists - a provider from before this was
 * recorded, a key since deleted - is kept and muted rather than dropped. The
 * money was spent either way, and a breakdown that silently stops adding up to
 * the total is worse than one with an honest "not recorded" line in it.
 *
 * `icon` is the row subject's own mark - a vendor's brand, a key glyph -
 * decorative beside the label that carries the fact, which is why it renders
 * aria-hidden. A muted row usually has none: its subject is exactly the thing
 * there is no mark left for.
 */
export function SpendBreakdown({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: {
    key: string;
    label: string;
    muted: boolean;
    runs: number;
    cost: string;
    icon?: ReactNode;
  }[];
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
              {row.icon !== undefined && (
                <span aria-hidden className="text-muted-foreground shrink-0">
                  {row.icon}
                </span>
              )}
              <span
                className={
                  row.muted ? "text-muted-foreground truncate italic" : "truncate font-medium"
                }
              >
                {row.label}
              </span>
              <span className="text-muted-foreground ml-auto text-xs whitespace-nowrap">
                {t("runCount", { count: row.runs })}
              </span>
              <span className="font-mono tabular-nums">${Number(row.cost).toFixed(4)}</span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
