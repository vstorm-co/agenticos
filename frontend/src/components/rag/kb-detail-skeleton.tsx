"use client";

import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui";
import { DocumentsTable } from "./documents-table";

const pending = () => {};

/** Reserve the collection header, tabs and the actual responsive document table. */
export function KBDetailSkeleton({
  tab = "documents",
  showGaps = false,
}: {
  tab?: "documents" | "ingestion" | "sync" | "gaps";
  showGaps?: boolean;
}) {
  const t = useTranslations("pages.kb");
  const gaps = useTranslations("knowledgeGaps");
  return (
    <div aria-busy="true" className="flex min-w-0 flex-1 flex-col">
      <div aria-hidden="true" className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-3">
          <Skeleton className="h-3 w-40 max-w-full" />
          <Skeleton className="h-8 w-56 max-w-full" />
          <Skeleton className="h-4 w-72 max-w-full" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="size-9 rounded-lg" />
          <Skeleton className="h-9 w-24 rounded-lg" />
        </div>
      </div>
      <div aria-hidden="true" className="mb-6 flex flex-wrap gap-4">
        {["w-16", "w-24", "w-20"].map((width) => (
          <Skeleton key={width} className={`h-4 ${width}`} />
        ))}
      </div>
      <div
        aria-hidden="true"
        className="border-border mb-2 flex min-w-0 gap-4 overflow-hidden border-b"
      >
        {[
          t("documents"),
          t("howDocumentsAreRead"),
          t("syncSources"),
          ...(showGaps ? [gaps("tab")] : []),
        ].map((label) => (
          <span
            key={label}
            className="text-muted-foreground shrink-0 px-3 py-2 text-sm font-medium"
          >
            {label}
          </span>
        ))}
      </div>
      {tab === "documents" ? (
        <DocumentsTable
          kbId=""
          documents={[]}
          documentsTotal={0}
          hasMoreDocuments={false}
          isLoading
          isLoadingMoreDocs={false}
          mayEdit={false}
          onLoadMore={pending}
          onPreview={pending}
          onRemove={pending}
          onChooseFiles={pending}
        />
      ) : (
        <div
          aria-hidden="true"
          className="border-border bg-card flex-1 space-y-5 rounded-xl border p-5"
        >
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-full max-w-lg" />
          <Skeleton className="h-32 w-full rounded-lg" />
        </div>
      )}
    </div>
  );
}
