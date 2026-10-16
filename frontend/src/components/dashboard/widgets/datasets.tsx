"use client";

import { useState } from "react";
import Link from "next/link";
import { FlaskConical, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { CreateDatasetDialog } from "@/components/datasets/create-dataset-dialog";
import { Button } from "@/components/ui/button";
import { useDatasets } from "@/hooks/use-datasets";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import type { CaseSource, Dataset } from "@/types/datasets";
import { Perm } from "@/types/permissions";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; the page behind "see all" has the rest. */
const SHOWN = 4;

const EXPECTATIONS = [
  ["with_reference", "reference"],
  ["with_counter_example", "counter"],
  ["with_tool_calls", "toolCalls"],
  ["with_checks", "checks"],
] as const;

const SOURCES: CaseSource[] = ["conversation", "import", "manual", "synthetic"];

/** What one dataset's newest version tests against: the counts that are not zero. */
function Breakdown({ dataset }: { dataset: Dataset }) {
  const t = useTranslations("dashboard.widgets.datasets");
  const { stats } = dataset;
  const sources = SOURCES.filter((source) => stats.by_source[source] > 0);
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
      {EXPECTATIONS.filter(([field]) => stats[field] > 0).map(([field, key]) => (
        <span key={key} className="bg-muted text-foreground/80 rounded px-1.5 py-0.5">
          {t(`stat.${key}`, { count: stats[field] })}
        </span>
      ))}
      {sources.length > 0 && (
        <span className="text-muted-foreground">
          {sources
            .map((source) => t(`source.${source}`, { count: stats.by_source[source] }))
            .join(" · ")}
        </span>
      )}
      {stats.top_tags.map(({ tag }) => (
        <span key={tag} className="text-muted-foreground">
          #{tag}
        </span>
      ))}
    </div>
  );
}

/**
 * The datasets changed most recently: how many cases each holds at which
 * version, and what those cases test against - good answers, bad ones, tool
 * calls, checks - and where they came from. The same listing the Datasets page
 * reads, first page only; the counts ride on it.
 */
export function DatasetsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.datasets");
  const tDatasets = useTranslations("datasets");
  const { can } = usePermissions();
  const [creating, setCreating] = useState(false);
  const { datasets, isLoading, error, refetch } = useDatasets({ sort: "updated", limit: SHOWN });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : datasets.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center">
          <WidgetEmptyBody
            icon={FlaskConical}
            title={t("empty.title")}
            description={t("empty.description")}
          />
          {can(Perm.datasetsEdit) && (
            <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
              <Plus className="h-3.5 w-3.5" aria-hidden />
              {tDatasets("newDataset")}
            </Button>
          )}
        </div>
      ) : (
        <ul className="divide-border divide-y">
          {datasets.map((dataset) => (
            <li key={dataset.id}>
              <Link
                href={`${ROUTES.DATASETS}/${dataset.id}`}
                className="hover:bg-accent/40 flex flex-col gap-1 rounded-md px-1 py-2"
              >
                <span className="flex items-center justify-between gap-3">
                  <span className="text-foreground truncate text-sm">{dataset.name}</span>
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {t("cases", { count: dataset.case_count, version: dataset.latest_version })}
                  </span>
                </span>
                {dataset.case_count > 0 && <Breakdown dataset={dataset} />}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {creating && <CreateDatasetDialog open onOpenChange={setCreating} />}
    </WidgetFrame>
  );
}
