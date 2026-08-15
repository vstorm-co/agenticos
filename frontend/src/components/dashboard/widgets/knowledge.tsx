"use client";

import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";
import { useKnowledgeBases } from "@/hooks";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * What the agents can actually read.
 *
 * `knowledge-freshness` answers whether a *sync source* has stopped bringing
 * documents in; this answers whether the documents that arrived ever finished
 * being indexed. A collection can be perfectly fresh and hold two hundred
 * documents nothing can retrieve, because parsing failed on every one of them
 * - and until this card, the only place that showed was inside the collection.
 *
 * `document_count` counts everything tracked, including rows still parsing and
 * rows that failed; `indexed_count` is how many finished. The gap between them
 * is the number worth a reader's attention, so it is the one drawn in the
 * warning tone rather than left for them to subtract.
 */
export function KnowledgeWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.knowledge");
  const { kbs, isLoading, listError, fetchKBs } = useKnowledgeBases();

  if (isLoading) {
    return (
      <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
        <WidgetSkeleton />
      </WidgetFrame>
    );
  }

  const documents = kbs.reduce((total, kb) => total + kb.document_count, 0);
  const indexed = kbs.reduce((total, kb) => total + kb.indexed_count, 0);
  const chunks = kbs.reduce((total, kb) => total + kb.chunk_count, 0);
  const unindexed = documents - indexed;

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {listError ? (
        <WidgetErrorBody onRetry={fetchKBs} />
      ) : kbs.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="grid flex-1 grid-cols-3 content-center gap-4">
          <Figure label={t("collections")} value={kbs.length.toLocaleString()} />
          <Figure
            label={t("documents")}
            value={documents.toLocaleString()}
            caption={unindexed > 0 ? t("notIndexed", { count: unindexed }) : undefined}
            captionTone={unindexed > 0 ? "destructive" : "muted"}
          />
          <Figure label={t("chunks")} value={chunks.toLocaleString()} />
        </div>
      )}
    </WidgetFrame>
  );
}
