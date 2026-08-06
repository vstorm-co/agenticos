"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Download,
  Eye,
  FileText,
  Loader2,
  Lock,
  MoreHorizontal,
  Plug,
  Plus,
  RefreshCw,
  RotateCw,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { ROUTES } from "@/lib/constants";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Progress,
  Skeleton,
  type Column,
} from "@/components/ui";
import { EmptyState } from "@/components/states";
import { SyncSourceWizard } from "@/components/rag/sync-source-wizard";
import { SyncSourceLogs } from "@/components/rag/sync-source-logs";
import { BrandIcon, connectorBrand } from "@/components/icons/brand-icon";
import { FileViewer } from "@/components/kb/file-viewer";
import { IngestionDialog } from "@/components/kb/ingestion-dialog";
import { IngestionPanel } from "@/components/kb/ingestion-panel";
import { UploadOverrideDialog } from "@/components/kb/upload-override-dialog";
import { useKBDetail, usePermissions, usePollWhileIngesting } from "@/hooks";
import { cn, formatBytes, formatDateTime } from "@/lib/utils";
import { overrideSize } from "@/lib/ingestion-config";
import { downloadKBDocument } from "@/lib/rag-api";
import type { SyncSourceRead } from "@/lib/rag-api";
import type { IngestionOverride, KBDocument, KBScope } from "@/types";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/**
 * How each scope is drawn: an icon, and the key to the word for it.
 *
 * A key rather than the word, because a table at module scope has no
 * translator to call - the component reads `t(labelKey)` at the point of use.
 * Spelled out here, these were three one-word strings, which is under
 * `check_i18n.py`'s two-word threshold and so rendered in English under `pl`.
 */
const SCOPE_META: Record<KBScope, { labelKey: string; icon: LucideIcon }> = {
  personal: { labelKey: "scopePersonal", icon: Lock },
  org: { labelKey: "scopeOrg", icon: Users },
  app: { labelKey: "scopeApp", icon: Sparkles },
};

// Sync sources have no server-side pagination (the backend returns every source
// for the KB's collection). They're typically few, so collapse past this count
// behind a client-side "show all" toggle.
const SYNC_SOURCES_VISIBLE = 10;

/**
 * The `DataTransfer` type a dragged file carries, spelled as the DOM spells it.
 *
 * A machine value, not copy - and it was in `messages/en.json` as `files2` and
 * `files3`, where a translator opening `pl.json` would have been asked to
 * translate it. "Pliki" is never in `dataTransfer.types`, so the whole
 * drag-and-drop path would have gone quiet under `pl` with nothing on screen
 * explaining it.
 */
const DRAGGED_FILES = "Files";

interface KBDetailPageProps {
  params: Promise<{ id: string }>;
}

export default function KBDetailPage({ params }: KBDetailPageProps) {
  const t = useTranslations("pages.kb");
  const router = useRouter();
  const { id } = use(params);
  const {
    kb,
    documents,
    documentsTotal,
    hasMoreDocuments,
    syncSources,
    orgIntegrations,
    connectors,
    isLoading,
    isLoadingMoreDocs,
    isUploading,
    uploadProgress,
    error,
    refresh,
    loadMoreDocuments,
    updateIngestion,
    uploadDocument,
    deleteDocument,
    deleteCollection,
    createSyncSource,
    cloneSyncSource,
    triggerSyncSource,
    deleteSyncSource,
  } = useKBDetail(id);

  // Presentation, never enforcement - the write routes resolve access per
  // row on the server. A Viewer holds `collections:view` only; offering them
  // upload and delete would be offering actions that can only refuse.
  const { can } = usePermissions();
  const mayEdit = can(Perm.collectionsEdit);

  const [isDragging, setIsDragging] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [creatingSource, setCreatingSource] = useState(false);
  const [syncSourcesExpanded, setSyncSourcesExpanded] = useState(false);
  const [viewerDoc, setViewerDoc] = useState<KBDocument | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [ingestionOpen, setIngestionOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  /**
   * What a destructive control has asked for and not yet been granted.
   *
   * Three of them, each held on the page rather than beside its button: the
   * document one is raised from a `DataTable` cell and the sync-source one from
   * a row component, and a dialog rendered inside either is a dialog inside a
   * subtree that re-renders on every poll. These were `window.confirm` calls
   * carrying hardcoded English, which is copy no locale and no `check_i18n.py`
   * sweep can reach.
   */
  const [deletingCollection, setDeletingCollection] = useState(false);
  const [removingDocument, setRemovingDocument] = useState<KBDocument | null>(null);
  const [disconnectingSource, setDisconnectingSource] = useState<SyncSourceRead | null>(null);
  /**
   * Whether a granted one is still in the air. One flag for all three, because
   * only one of these dialogs can be open at a time - and without it the confirm
   * button stays live through the request, so a second click sends a second
   * DELETE and the 404 it earns is toasted over a removal that worked.
   */
  const [confirmBusy, setConfirmBusy] = useState(false);
  /**
   * How the next files added here are to be read, where that is not how the
   * collection reads them.
   *
   * Held on the page rather than inside a dialog because a file arrives three
   * ways - the button, the file dialog, a drag onto anywhere on this page - and
   * all three have to carry it. Kept until it is cleared, since a drag can be a
   * batch; the banner below is what stops that from being a surprise.
   */
  const [uploadOverride, setUploadOverride] = useState<IngestionOverride>({});
  const overrideCount = overrideSize(uploadOverride);
  /**
   * Chunks across the documents this page has actually fetched.
   *
   * Not the collection's total, and it cannot be: no response this page makes
   * carries one. The strip below says which of the two it is showing.
   */
  const loadedVectors = documents.reduce((sum, doc) => sum + doc.chunk_count, 0);

  const handleDownload = async (doc: KBDocument) => {
    if (downloadingId) return;
    setDownloadingId(doc.id);
    try {
      await downloadKBDocument(id, doc, "download");
    } catch {
      /* silently ignore */
    } finally {
      setDownloadingId(null);
    }
  };

  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounterRef = useRef(0);

  useEffect(() => {
    refresh();
  }, [refresh]);

  usePollWhileIngesting(documents, refresh);

  const handleFiles = async (files: FileList | null) => {
    if (!mayEdit || !files || files.length === 0) return;
    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file, uploadOverride);
      } catch {
        /* toast handled in hook */
      }
    }
  };

  const documentColumns = useMemo<Column<KBDocument>[]>(
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
        cell: (doc) => <Provenance doc={doc} />,
      },
      {
        key: "status",
        header: t("status2"),
        cell: (doc) => <StatusBadge status={doc.status} message={doc.error_message} />,
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
                    onClick={() => setViewerDoc(doc)}
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
                  onClick={() => setRemovingDocument(doc)}
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
    [downloadingId, handleDownload, setViewerDoc, mayEdit],
  );

  if (isLoading && !kb) return <KBDetailSkeleton />;
  if (error && !kb) {
    return (
      <div className="text-destructive flex h-64 items-center justify-center text-sm">{error}</div>
    );
  }
  if (!kb) return null;

  const scopeMeta = SCOPE_META[kb.scope];

  return (
    <div
      className="relative pb-8"
      onDragEnter={(e) => {
        if (e.dataTransfer.types.includes(DRAGGED_FILES)) {
          dragCounterRef.current += 1;
          setIsDragging(true);
        }
      }}
      onDragLeave={() => {
        dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
        if (dragCounterRef.current === 0) setIsDragging(false);
      }}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(DRAGGED_FILES)) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        dragCounterRef.current = 0;
        setIsDragging(false);
        handleFiles(e.dataTransfer.files);
      }}
    >
      {isDragging && (
        <div className="bg-background/80 fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm">
          <div className="border-foreground/30 bg-card flex flex-col items-center gap-4 rounded-xl border-2 border-dashed px-12 py-16">
            <span className="bg-muted text-foreground inline-flex h-14 w-14 items-center justify-center rounded-xl">
              <Upload className="h-6 w-6" />
            </span>
            <div className="text-center">
              <p className="text-foreground text-lg font-semibold">{t("dropUpload")}</p>
              <p className="text-muted-foreground mt-1 text-sm">
                {t.rich("filesWillBeAddedTo", {
                  name: kb.name,
                  strong: (chunks) => <span className="text-foreground font-medium">{chunks}</span>,
                })}
              </p>
            </div>
          </div>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
        disabled={isUploading}
      />

      <PageHeader
        breadcrumbs={[{ label: t("knowledgeBases"), href: ROUTES.KB }, { label: kb.name }]}
        title={kb.name}
        description={
          kb.description || <span className="font-mono text-xs">{kb.collection_name}</span>
        }
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => refresh()} disabled={isLoading}>
              <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
              {t("refresh")}
            </Button>
            {mayEdit && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setOverrideOpen(true)}
                  disabled={isUploading}
                >
                  <SlidersHorizontal className="h-4 w-4" />
                  {t("parseOptions")}
                </Button>
                <Button
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploading}
                >
                  {isUploading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                  {isUploading ? t("uploading") : t("upload")}
                </Button>
                {/* Behind a menu, not beside Refresh: destroying the collection
                    and everything in it is not a same-weight sibling of
                    re-reading it. It lives here rather than on the card in the
                    list because this is the page that says what is inside.

                    Not drawn at all for the default collection, which
                    `KnowledgeBaseService.delete` refuses outright - offering it
                    would be offering an action that can only answer 400. The
                    card in the list hid it for the same reason. */}
                {!kb.is_default && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-8 px-0"
                        aria-label={t("moreActions")}
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onSelect={() => setDeletingCollection(true)}
                      >
                        <Trash2 className="h-4 w-4" />
                        {t("deleteKnowledgeBase")}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </>
            )}
          </>
        }
      />

      {/* What the collection holds, not what the table has fetched.

          `documents` is one page of twenty, so this strip used to say "20
          documents" over a collection of fifty-seven and then climb every time
          Load more was pressed - which reads as ingestion happening rather than
          as the page correcting itself. `documentsTotal` is the documents
          query's own total; `kb.document_count` is not an alternative, because
          the single-row `GET /kb/{id}` leaves all three counts at zero.

          The vector count has no such total in any response this page makes, so
          it says which it is. Once every document is loaded the sum *is* the
          collection's, and it says so plainly; until then it names its own
          scope rather than passing a partial sum off as the whole. */}
      <div className="text-muted-foreground mb-6 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <span className="inline-flex items-center gap-1.5">
          <scopeMeta.icon className="h-3.5 w-3.5" />
          {t(scopeMeta.labelKey)}
          {kb.is_default && ` · ${t("default")}`}
        </span>
        <span>·</span>
        <span>{t("documentCount", { count: documentsTotal })}</span>
        <span>·</span>
        <span>
          {hasMoreDocuments
            ? t("vectorCountLoaded", { count: loadedVectors })
            : t("vectorCount", { count: loadedVectors })}
        </span>
      </div>

      {/*
        Loud on purpose, and it stays until it is dismissed. A departure that
        applies to whatever is dropped next, remembered quietly, is how somebody
        re-parses a batch with settings they set twenty minutes ago.
      */}
      {overrideCount > 0 && (
        <div className="border-brand-line bg-brand-subtle mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3">
          <p className="text-foreground text-sm">
            {t.rich("parsedWithOverrides", {
              count: overrideCount,
              strong: (chunks) => <span className="font-medium">{chunks}</span>,
            })}{" "}
            <span className="text-muted-foreground">{t("collectionItselfUnchanged")}</span>
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setOverrideOpen(true)}>
              {t("review")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setUploadOverride({})}>
              {t("clear")}
            </Button>
          </div>
        </div>
      )}

      {uploadProgress.length > 0 && (
        <section className="border-border bg-card mb-6 space-y-3 rounded-xl border p-4">
          {uploadProgress.map((up) => (
            <div key={up.uploadId}>
              <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                <span className="text-foreground flex min-w-0 items-center gap-2 font-medium">
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  <span className="truncate" title={up.filename}>
                    {up.filename}
                  </span>
                </span>
                <span className="text-muted-foreground shrink-0 tabular-nums">
                  {up.percent === null
                    ? t("uploading2")
                    : up.percent >= 100
                      ? t("processing")
                      : `${up.percent}%`}
                </span>
              </div>
              <Progress
                value={up.percent ?? undefined}
                className={cn(up.percent === null && "animate-pulse")}
              />
            </div>
          ))}
        </section>
      )}

      <section className="mb-8">
        <h2 className="text-foreground mb-3 text-sm font-semibold">{t("documents")}</h2>
        <DataTable<KBDocument>
          columns={documentColumns}
          rows={documents}
          getRowKey={(doc) => doc.id}
          loading={isLoading && documents.length === 0}
          empty={
            <EmptyState
              icon={Upload}
              title={t("noDocumentsYet")}
              description={mayEdit ? t("dragFilesAnywherePage") : t("nothingHasBeenUploaded")}
              cta={
                mayEdit
                  ? { label: t("chooseFiles"), onClick: () => fileInputRef.current?.click() }
                  : undefined
              }
            />
          }
        />
        {documents.length > 0 && (
          <div className="mt-3 flex flex-col items-center gap-2">
            {hasMoreDocuments && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => loadMoreDocuments()}
                disabled={isLoadingMoreDocs}
              >
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

      {/* Under the documents, because it is the answer to a question the table
          above raises: the parser column says what read each file, and this says
          what will read the next one. */}
      <div className="mb-8">
        <IngestionPanel kb={kb} onEdit={mayEdit ? () => setIngestionOpen(true) : undefined} />
      </div>

      <section>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-foreground text-sm font-semibold">{t("syncSources")}</h2>
          {mayEdit && connectors.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => setWizardOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("connect")}
            </Button>
          )}
        </div>

        {syncSources.length === 0 ? (
          <EmptyState
            icon={Plug}
            title={connectors.length > 0 ? t("noSourcesConnected") : t("noConnectorsConfigured")}
            description={
              connectors.length > 0 ? t("addOneKeepKnowledge") : t("configureConnectorsAtWorkspace")
            }
            cta={
              mayEdit && connectors.length > 0
                ? { label: t("connectSource"), onClick: () => setWizardOpen(true) }
                : undefined
            }
          />
        ) : (
          <>
            <ul className="border-border bg-card divide-border divide-y overflow-hidden rounded-xl border">
              {(syncSourcesExpanded ? syncSources : syncSources.slice(0, SYNC_SOURCES_VISIBLE)).map(
                (source) => (
                  <SyncSourceRow
                    key={source.id}
                    source={source}
                    kbId={id}
                    onTrigger={mayEdit ? () => triggerSyncSource(source.id) : undefined}
                    onDelete={mayEdit ? () => setDisconnectingSource(source) : undefined}
                  />
                ),
              )}
            </ul>
            {syncSources.length > SYNC_SOURCES_VISIBLE && (
              <div className="mt-3 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSyncSourcesExpanded((v) => !v)}
                >
                  {syncSourcesExpanded
                    ? t("showLess")
                    : t("showAllSources", { count: syncSources.length })}
                </Button>
              </div>
            )}
          </>
        )}
      </section>

      {/* The count is the collection's, not the table's. Documents page in
          twenty at a time, so `documents.length` would promise to destroy far
          less than the confirm button actually does. */}
      <ConfirmDialog
        open={deletingCollection}
        onOpenChange={setDeletingCollection}
        title={t("deleteCollectionTitle", { name: kb.name })}
        description={t("deleteCollectionWarning", { count: documentsTotal })}
        confirmLabel={t("delete")}
        destructive
        loading={confirmBusy}
        onConfirm={async () => {
          setConfirmBusy(true);
          try {
            await deleteCollection();
          } catch {
            // The hook has already said why. The collection is still there, so
            // this page is still the right one to be on.
            setConfirmBusy(false);
            return;
          }
          // Closed before the navigation rather than left to the unmount: a
          // client route change is not instant, and a modal frozen on its busy
          // label with Cancel disabled is the last thing this page would say.
          setConfirmBusy(false);
          setDeletingCollection(false);
          router.push(ROUTES.KB);
        }}
      />

      {removingDocument && (
        <ConfirmDialog
          open
          onOpenChange={() => setRemovingDocument(null)}
          title={t("removeDocumentTitle", { filename: removingDocument.filename })}
          description={t("removeDocumentWarning")}
          confirmLabel={t("remove")}
          destructive
          loading={confirmBusy}
          onConfirm={async () => {
            setConfirmBusy(true);
            // `finally`, though `deleteDocument` toasts rather than throwing:
            // the day it stops swallowing, the alternative is a dialog with
            // both buttons dead and an unhandled rejection behind it.
            try {
              await deleteDocument(removingDocument.id);
            } finally {
              setConfirmBusy(false);
              setRemovingDocument(null);
            }
          }}
        />
      )}

      {disconnectingSource && (
        <ConfirmDialog
          open
          onOpenChange={() => setDisconnectingSource(null)}
          title={t("disconnectSourceTitle", { name: disconnectingSource.name })}
          description={t("disconnectSourceWarning")}
          confirmLabel={t("disconnect")}
          destructive
          loading={confirmBusy}
          onConfirm={async () => {
            setConfirmBusy(true);
            try {
              await deleteSyncSource(disconnectingSource.id);
            } finally {
              setConfirmBusy(false);
              setDisconnectingSource(null);
            }
          }}
        />
      )}

      <FileViewer
        kbId={id}
        doc={viewerDoc}
        open={viewerDoc !== null}
        onClose={() => setViewerDoc(null)}
      />

      <IngestionDialog
        open={ingestionOpen}
        onOpenChange={setIngestionOpen}
        config={kb.ingestion_config}
        collectionName={kb.collection_name}
        onSave={updateIngestion}
      />

      <UploadOverrideDialog
        open={overrideOpen}
        onOpenChange={setOverrideOpen}
        config={kb.ingestion_config}
        override={uploadOverride}
        onApply={setUploadOverride}
      />

      <SyncSourceWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        connectors={connectors}
        collections={[{ name: kb.collection_name }]}
        defaultCollection={kb.collection_name}
        orgIntegrations={orgIntegrations}
        submitting={creatingSource}
        onSubmit={async (data) => {
          setCreatingSource(true);
          try {
            await createSyncSource(data);
            setWizardOpen(false);
          } catch {
            /* toast handled in hook */
          } finally {
            setCreatingSource(false);
          }
        }}
        onClone={async (sourceId, collectionName, name) => {
          setCreatingSource(true);
          try {
            await cloneSyncSource(sourceId, collectionName, name);
            setWizardOpen(false);
          } catch {
            /* toast handled in hook */
          } finally {
            setCreatingSource(false);
          }
        }}
      />
    </div>
  );
}

/** Skeleton mirroring the page layout: header, meta strip, and a few doc rows. */
function KBDetailSkeleton() {
  return (
    <div className="pb-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24 rounded-lg" />
          <Skeleton className="h-9 w-24 rounded-lg" />
        </div>
      </div>

      <Skeleton className="mb-6 h-4 w-64" />

      <Skeleton className="mb-3 h-4 w-24" />
      <div className="border-border bg-card divide-border divide-y overflow-hidden rounded-xl border">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="h-8 w-8 shrink-0 rounded-lg" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

function SyncSourceRow({
  source,
  kbId,
  onTrigger,
  onDelete,
}: {
  source: SyncSourceRead;
  kbId: string;
  /** Absent when the caller may not write - the buttons are then not drawn. */
  onTrigger?: () => void;
  /** Asks for the disconnection; the page owns the confirmation and the call. */
  onDelete?: () => void;
}) {
  const t = useTranslations("pages.kb");
  const lastSync = source.last_sync_at ? formatDateTime(source.last_sync_at) : t("never");
  const brand = connectorBrand(source.connector_type);
  return (
    <li className="overflow-hidden">
      <div className="hover:bg-accent flex items-center gap-3 px-4 py-3 transition-colors">
        <span className="bg-muted text-muted-foreground inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
          {brand ? (
            <BrandIcon name={brand} className="h-4 w-4" />
          ) : (
            <Plug className="h-3.5 w-3.5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-foreground truncate text-sm font-medium">{source.name}</p>
          </div>
          <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2 text-xs">
            <span>{t("lastSyncAt", { when: lastSync })}</span>
            {source.schedule_minutes && source.schedule_minutes > 0 && (
              <>
                <span>·</span>
                <span>{t("everyMinutes", { minutes: source.schedule_minutes })}</span>
              </>
            )}
          </div>
        </div>
        {source.last_sync_status && (
          <SyncStatusBadge status={source.last_sync_status} message={source.last_error} />
        )}
        {onTrigger && (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-foreground h-8 w-8 p-0"
            onClick={onTrigger}
            title={t("triggerSyncNow")}
            aria-label={t("triggerSyncNow2")}
          >
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
        )}
        {onDelete && (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
            onClick={onDelete}
            title={t("removeSource")}
            aria-label={t("removeSource2")}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
      <SyncSourceLogs logsPath={`/kb/${kbId}/sync-sources/${source.id}/logs`} />
    </li>
  );
}

/**
 * What actually read one document, and whether that was the collection's doing.
 *
 * `was_overridden` is the answer to a question asked long after the fact, so it
 * is worth a badge rather than a tooltip: the collection's settings move on, and
 * a document parsed under the old ones looks identical to one somebody chose to
 * parse differently.
 *
 * A document ingested before any of this was recorded says so, rather than
 * naming the collection's current parser - which would be a guess, and the kind
 * that is impossible to catch.
 */
function Provenance({ doc }: { doc: KBDocument }) {
  const t = useTranslations("pages.kb");
  if (doc.parser === null) {
    return <span className="text-muted-foreground text-xs">{t("notRecorded")}</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span
        className="text-muted-foreground font-mono text-xs"
        title={
          doc.embedding_model === null
            ? undefined
            : t("embeddedWith", { model: doc.embedding_model })
        }
      >
        {doc.parser}
      </span>
      {doc.image_description_model !== null && (
        <span
          className="text-muted-foreground text-xs"
          title={t("imagesDescribedBy", { model: doc.image_description_model })}
        >
          {t("images")}
        </span>
      )}
      {doc.was_overridden && <Badge variant="secondary">{t("overridden")}</Badge>}
    </div>
  );
}

function StatusBadge({ status, message }: { status: string; message: string | null }) {
  const t = useTranslations("pages.kb");
  // Four one-word labels, which is under `check_i18n.py`'s two-word threshold -
  // so they sat here in English and rendered that way under every locale. The
  // fall-through keeps the server's own word for a status this build does not
  // know: a value nothing has translated, rather than copy somebody wrote.
  const config = {
    completed: { Icon: CheckCircle2, label: t("statusReady"), spin: false },
    processing: { Icon: Loader2, label: t("statusProcessing"), spin: true },
    pending: { Icon: Clock, label: t("statusPending"), spin: false },
    failed: { Icon: AlertCircle, label: t("statusFailed"), spin: false },
  } as const;
  const c = (config as Record<string, (typeof config)[keyof typeof config]>)[status] ?? {
    Icon: Clock,
    label: status,
    spin: false,
  };
  return (
    <Badge
      variant="outline"
      title={message ?? undefined}
      className={cn(
        "border-border gap-1 font-normal",
        status === "failed" ? "text-destructive" : "text-muted-foreground",
      )}
    >
      <c.Icon className={cn("h-3 w-3", c.spin && "animate-spin")} />
      {c.label}
    </Badge>
  );
}

function SyncStatusBadge({ status, message }: { status: string; message: string | null }) {
  return (
    <Badge
      variant="outline"
      title={message ?? undefined}
      className={cn(
        "border-border shrink-0 font-normal",
        status === "failed" ? "text-destructive" : "text-muted-foreground",
      )}
    >
      {status}
    </Badge>
  );
}
