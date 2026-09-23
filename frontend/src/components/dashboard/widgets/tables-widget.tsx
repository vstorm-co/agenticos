"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Table2 } from "lucide-react";

import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";
import { useTables } from "@/hooks";
import { ROUTES } from "@/lib/constants";

/** How many tables the card lists before it defers to the page. */
const SHOWN = 6;

/**
 * The caller's tables, most-recently-updated first, each linking straight to
 * its detail page - the glanceable state the `/tables` catalog otherwise
 * requires a whole navigation to see.
 */
export function TablesWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.tables");
  // Sorted server-side: the six *most recently changed* tables, not the six
  // alphabetically-first ones re-sorted after the fact - a page of `limit`
  // rows ordered by name could never contain a table that only happens to
  // sort late.
  const {
    tables: rows,
    isLoading,
    error,
    refetch,
  } = useTables({ sort: "updated_at", limit: SHOWN });

  if (isLoading) {
    return (
      <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
        <WidgetSkeleton />
      </WidgetFrame>
    );
  }

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <WidgetEmptyBody
          icon={Table2}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y">
          {rows.map((table) => (
            <li key={table.id}>
              <Link
                href={ROUTES.TABLE_DETAIL(table.id)}
                className="hover:bg-accent flex items-center justify-between gap-2 py-1.5 text-sm"
              >
                <span className="truncate">{table.name}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
