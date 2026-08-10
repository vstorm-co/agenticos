"use client";

import { useMemo, useState } from "react";
import { Download, Eye, FileText, Loader2, Trash2, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, DataTable, type Column } from "@/components/ui";
import { EmptyState } from "@/components/states";
import { DocumentProvenance } from "@/components/rag/document-cells";
import { RagStatusBadge } from "@/components/rag/rag-status-badge";
import { kbDocumentAccess } from "@/lib/rag-api";
import { formatBytes } from "@/lib/utils";
import type { KBDocument } from "@/types";

/**
 * What a collection holds, one page at a time.
 *
 * `documentsTotal` is the collection's count and `documents` is the page in
 * hand, which is why the line under the table names both: without it, Load more
 * reads as documents appearing rather than as the table catching up.
 *
 * Preview and removal are asked for rather than done here - the viewer and the
 * confirmation both live on the page, because a dialog rendered inside a table
 * that re-renders on every ingestion poll is a dialog that closes itself.
 */
export function DocumentsTable({
  kbId,
  documents,
  documentsTotal,
  hasMoreDocuments,
  isLoading,
  isLoadingMoreDocs,
  mayEdit,
  onLoadMore,
  onPreview,
  onRemove,
  onChooseFiles,
}: {
  kbId: string;
  documents: KBDocument[];
  /** The collection's count, not the table's. */
  documentsTotal: number;
  hasMoreDocuments: boolean;
  isLoading: boolean;
  isLoadingMoreDocs: boolean;
  mayEdit: boolean;
  onLoadMore: () => void;
  onPreview: (doc: KBDocument) => void;
  onRemove: (doc: KBDocument) => void;
  onChooseFiles: () => void;
}) {
  const t = useTranslations("pages.kb");
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const handleDownload = async (doc: KBDocument) => {
    if (downloadingId) return;
    setDownloadingId(doc.id);
    try {
      await kbDocumentAccess(kbId, doc).download();
    } catch {
      /* silently ignore */
    } finally {
      setDownloadingId(null);
    }
  };

  const columns = useMemo<Column<KBDocument>[]>(
    () => [
      {
        key: "filename",
        header: t("name"),
        cell: (doc) => (
          <div className="flex min-w-0 items-center gap-3">
            <span className="bg-muted text-muted-foreground inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
              <FileText className="h-3.5 w-3.5" />
            </span>
            <span className="text-foreground truncate font-medium" title={doc.filename}>
              {doc.filename}
            </span>
          </div>
        ),
      },
      {
        key: "filetype",
        header: t("typeSize"),
        className: "hidden sm:table-cell",
        cell: (doc) => (
          <span className="text-muted-foreground text-xs">
            {doc.filetype || "-"}
            {doc.filesize !== null && ` · ${formatBytes(doc.filesize)}`}
            {doc.chunk_count > 0 && ` · ${t("chunkCount", { count: doc.chunk_count })}`}
          </span>
        ),
      },
      {
        // What read *this* document, which is not always what the collection is
        // set to now. Without it, "why did this one come out differently" has no
        // answer on any screen.
        key: "parser",
        header: t("parsedWith"),
        className: "hidden md:table-cell",
        cell: (doc) => <DocumentProvenance doc={doc} />,
      },
      {
        key: "status",
        header: t("status2"),
        cell: (doc) => <RagStatusBadge status={doc.status} message={doc.error_message} />,
      },
      {
        key: "actions",
        header: "",
        align: "right",
        className: "w-0",
        cell: (doc) => {
          const dlBusy = downloadingId === doc.id;
          return (
            <div className="flex items-center gap-0.5">
              {doc.has_file && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-foreground h-8 w-8 p-0"
                    onClick={() => onPreview(doc)}
                    title={t("previewFile")}
                    aria-label={t("previewFile2")}
                  >
                    <Eye className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-foreground h-8 w-8 p-0"
                    onClick={() => handleDownload(doc)}
                    disabled={!!downloadingId}
                    title={t("downloadFile")}
                    aria-label={t("downloadFile2")}
                  >
                    {dlBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Download className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </>
              )}
              {mayEdit && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
                  onClick={() => onRemove(doc)}
                  title={t("removeDocument")}
                  aria-label={t("removeDocument2")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          );
        },
      },
    ],
    [downloadingId, handleDownload, onPreview, onRemove, mayEdit],
  );

  return (
    <section className="mb-8" data-tour="kb-documents">
      <h2 className="text-foreground mb-3 text-sm font-semibold">{t("documents")}</h2>
      <DataTable<KBDocument>
        columns={columns}
        rows={documents}
        getRowKey={(doc) => doc.id}
        loading={isLoading && documents.length === 0}
        empty={
          <EmptyState
            icon={Upload}
            title={t("noDocumentsYet")}
            description={mayEdit ? t("dragFilesAnywherePage") : t("nothingHasBeenUploaded")}
            cta={mayEdit ? { label: t("chooseFiles"), onClick: onChooseFiles } : undefined}
          />
        }
      />
      {documents.length > 0 && (
        <div className="mt-3 flex flex-col items-center gap-2">
          {hasMoreDocuments && (
            <Button variant="outline" size="sm" onClick={onLoadMore} disabled={isLoadingMoreDocs}>
              {isLoadingMoreDocs && <Loader2 className="h-4 w-4 animate-spin" />}
              {isLoadingMoreDocs ? t("loading") : t("loadMore")}
            </Button>
          )}
          {/* The count is for everybody; the hint beside it is an instruction
              to do something a Viewer cannot, so it is gated like every other
              write affordance on this page rather than rendered and refused. */}
          <p className="text-muted-foreground text-center text-xs">
            {t("showingOfTotal", { loaded: documents.length, total: documentsTotal })}
            {mayEdit && (
              <>
                {" · "}
                {t("dragFilesToAdd")}
              </>
            )}
          </p>
        </div>
      )}
    </section>
  );
}
