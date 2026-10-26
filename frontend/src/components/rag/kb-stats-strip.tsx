"use client";

import { CircleAlert, CircleCheck, Loader2, Lock, Sparkles, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import type { RAGCollectionInfo } from "@/lib/rag-api";
import type { KBScope } from "@/types";

/**
 * How each scope is drawn: an icon, and the key to the word for it.
 *
 * A key rather than the word, because a table at module scope has no
 * translator to call - the component reads `t(labelKey)` at the point of use.
 * Spelled out here, these were three one-word strings, which sat under the old
 * guard's two-word threshold and so rendered in English under `pl`. There is no
 * threshold left to sit under - #395 replaced it with a parser.
 */
const SCOPE_META: Record<KBScope, { labelKey: string; icon: LucideIcon }> = {
  personal: { labelKey: "scopePersonal", icon: Lock },
  org: { labelKey: "scopeOrg", icon: Users },
  app: { labelKey: "scopeApp", icon: Sparkles },
};

/**
 * What the collection holds, not what the table below has fetched.
 *
 * `documents` is one page of twenty, so this strip used to say "20 documents"
 * over a collection of fifty-seven and then climb every time Load more was
 * pressed - which reads as ingestion happening rather than as the page
 * correcting itself. `documentsTotal` is the documents query's own total;
 * `kb.document_count` is not an alternative, because the single-row
 * `GET /kb/{id}` leaves all three counts at zero.
 *
 * The vector count has no such total in any response this page makes, so it
 * says which it is. Once every document is loaded the sum *is* the
 * collection's, and it says so plainly; until then it names its own scope
 * rather than passing a partial sum off as the whole.
 *
 * `ingestion` is whether the collection is still indexing, counted over every
 * document rather than the loaded page, and `null` until it has answered or when
 * it could not - the strip then says nothing about it rather than guessing. It
 * says indexing is complete only once something has been indexed, so an empty
 * collection is not announced as finished; a failed document is shown beside
 * either state, since it does not hold the collection at indexing (#2486).
 */
export function KBStatsStrip({
  scope,
  isDefault,
  documentsTotal,
  loadedVectors,
  hasMoreDocuments,
  ingestion,
}: {
  scope: KBScope;
  isDefault: boolean;
  documentsTotal: number;
  /** Chunks across the documents fetched so far, which may not be all of them. */
  loadedVectors: number;
  hasMoreDocuments: boolean;
  ingestion: RAGCollectionInfo | null;
}) {
  const t = useTranslations("pages.kb");
  const meta = SCOPE_META[scope];
  return (
    <div className="text-muted-foreground mb-6 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <span className="inline-flex items-center gap-1.5">
        <meta.icon className="h-3.5 w-3.5" />
        {t(meta.labelKey)}
        {isDefault && ` · ${t("default")}`}
      </span>
      <span>·</span>
      <span>{t("documentCount", { count: documentsTotal })}</span>
      <span>·</span>
      <span>
        {hasMoreDocuments
          ? t("vectorCountLoaded", { count: loadedVectors })
          : t("vectorCount", { count: loadedVectors })}
      </span>
      {ingestion?.indexing_status === "indexing" && (
        <>
          <span>·</span>
          <span className="inline-flex items-center gap-1.5" role="status">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("indexingInProgress", { count: ingestion.processing_count })}
          </span>
        </>
      )}
      {ingestion?.indexing_status === "complete" && ingestion.indexed_count > 0 && (
        <>
          <span>·</span>
          <span className="inline-flex items-center gap-1.5" role="status">
            <CircleCheck className="h-3.5 w-3.5" />
            {t("indexingComplete")}
          </span>
        </>
      )}
      {ingestion !== null && ingestion.failed_count > 0 && (
        <>
          <span>·</span>
          <span className="text-destructive inline-flex items-center gap-1.5">
            <CircleAlert className="h-3.5 w-3.5" />
            {t("indexingFailed", { count: ingestion.failed_count })}
          </span>
        </>
      )}
    </div>
  );
}
