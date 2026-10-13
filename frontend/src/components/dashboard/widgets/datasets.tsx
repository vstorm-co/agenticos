"use client";

import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

import { useDatasets } from "@/hooks/use-datasets";
import { ROUTES } from "@/lib/constants";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; the page behind "see all" has the rest. */
const SHOWN = 5;

/**
 * The datasets changed most recently, with how many cases each holds and at
 * which version - the set the next eval run would answer. The same listing the
 * Datasets page reads, first page only.
 */
export function DatasetsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.datasets");
  const { datasets, isLoading, error, refetch } = useDatasets({ sort: "updated", limit: SHOWN });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : datasets.length === 0 ? (
        <WidgetEmptyBody
          icon={FlaskConical}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y">
          {datasets.map((dataset) => (
            <li key={dataset.id}>
              <Link
                href={`${ROUTES.DATASETS}/${dataset.id}`}
                className="hover:bg-accent/40 flex items-center justify-between gap-3 rounded-md px-1 py-2"
              >
                <span className="text-foreground truncate text-sm">{dataset.name}</span>
                <span className="text-muted-foreground shrink-0 text-xs">
                  {t("cases", { count: dataset.case_count, version: dataset.latest_version })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
