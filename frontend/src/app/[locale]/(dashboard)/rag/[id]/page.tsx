"use client";

import { use, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ROUTES } from "@/lib/constants";
import { Button, ConfirmDialog, Alert, AlertDescription, AlertTitle } from "@/components/ui";
import { SyncSourceWizard } from "@/components/rag/sync-source-wizard";
import { KBDetailSkeleton } from "@/components/rag/kb-detail-skeleton";
import { KBDetailHeader } from "@/components/rag/kb-detail-header";
import { KBStatsStrip } from "@/components/rag/kb-stats-strip";
import { FileDropZone } from "@/components/rag/file-drop-zone";
import { UploadProgressList } from "@/components/rag/upload-progress-list";
import { DocumentsTable } from "@/components/rag/documents-table";
import { SyncSourcesSection } from "@/components/rag/sync-sources-section";
import { FileViewer } from "@/components/kb/file-viewer";
import { IngestionDialog } from "@/components/kb/ingestion-dialog";
import { IngestionPanel } from "@/components/kb/ingestion-panel";
import { UploadOverrideDialog } from "@/components/kb/upload-override-dialog";
import { useKBDetail, usePermissions, usePollWhileIngesting } from "@/hooks";
import { overrideSize } from "@/lib/ingestion-config";
import type { SyncSourceRead } from "@/lib/rag-api";
import type { IngestionOverride, KBDocument } from "@/types";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

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
    sectionFailures,
    isLoading,
    loadFailed,
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

  const [wizardOpen, setWizardOpen] = useState(false);
  const [creatingSource, setCreatingSource] = useState(false);
  const [viewerDoc, setViewerDoc] = useState<KBDocument | null>(null);
  const [ingestionOpen, setIngestionOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  /**
   * What a destructive control has asked for and not yet been granted.
   *
   * Three of them, each held on the page rather than beside its button: the
   * document one is raised from a `DataTable` cell and the sync-source one from
   * a row component, and a dialog rendered inside either is a dialog inside a
   * subtree that re-renders on every poll. These were `window.confirm` calls
   * carrying hardcoded English, which no locale could reach and no guard reported
   * either, until #395 started reading a call's arguments.
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

  const fileInputRef = useRef<HTMLInputElement>(null);

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

  if (isLoading && !kb) return <KBDetailSkeleton />;
  // A cold failure of a load-bearing read - the collection or its documents -
  // takes the whole page. A failed *refresh* does not reach here: it keeps `kb`
  // and shows the "may be stale" banner below instead.
  if (loadFailed) {
    return (
      <div className="text-destructive flex h-64 items-center justify-center text-sm">{error}</div>
    );
  }
  if (!kb) return null;

  return (
    <FileDropZone collectionName={kb.name} onFiles={handleFiles}>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
        disabled={isUploading}
      />

      <div data-tour="kb-header">
        <KBDetailHeader
          kb={kb}
          mayEdit={mayEdit}
          isLoading={isLoading}
          isUploading={isUploading}
          onRefresh={() => refresh()}
          onEditParseOptions={() => setOverrideOpen(true)}
          onChooseFiles={() => fileInputRef.current?.click()}
          onDelete={() => setDeletingCollection(true)}
        />
      </div>

      <KBStatsStrip
        scope={kb.scope}
        isDefault={kb.is_default}
        documentsTotal={documentsTotal}
        loadedVectors={loadedVectors}
        hasMoreDocuments={hasMoreDocuments}
      />

      {/* Reached only with a `kb` in hand, so this is a refresh that failed, with
          the sections below still showing the last good answer. */}
      {error && (
        <Alert
          variant="destructive"
          className="mb-6 flex flex-wrap items-center justify-between gap-3"
        >
          <div>
            <AlertTitle>{t("refreshFailedTitle")}</AlertTitle>
            <AlertDescription className="text-destructive/80">
              {t("refreshFailedDescription")}
              <p className="mt-1 text-xs opacity-75">{error}</p>
            </AlertDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => refresh()} disabled={isLoading}>
            {t("retry")}
          </Button>
        </Alert>
      )}

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

      <UploadProgressList uploads={uploadProgress} />

      <DocumentsTable
        kbId={id}
        documents={documents}
        documentsTotal={documentsTotal}
        hasMoreDocuments={hasMoreDocuments}
        isLoading={isLoading}
        isLoadingMoreDocs={isLoadingMoreDocs}
        mayEdit={mayEdit}
        onLoadMore={() => loadMoreDocuments()}
        onPreview={setViewerDoc}
        onRemove={setRemovingDocument}
        onChooseFiles={() => fileInputRef.current?.click()}
      />

      {/* Under the documents, because it is the answer to a question the table
          above raises: the parser column says what read each file, and this says
          what will read the next one. */}
      <div className="mb-8" data-tour="kb-ingestion">
        <IngestionPanel kb={kb} onEdit={mayEdit ? () => setIngestionOpen(true) : undefined} />
      </div>

      <SyncSourcesSection
        kbId={id}
        syncSources={syncSources}
        connectors={connectors}
        syncSourcesFailed={sectionFailures.syncSources}
        connectorsFailed={sectionFailures.connectors}
        mayEdit={mayEdit}
        onConnect={() => setWizardOpen(true)}
        onTrigger={(sourceId) => triggerSyncSource(sourceId)}
        onDisconnect={setDisconnectingSource}
        onRetry={() => refresh()}
      />

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
          router.push(ROUTES.RAG);
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
        connectorsFailed={sectionFailures.connectors}
        orgIntegrationsFailed={sectionFailures.orgIntegrations}
        submitting={creatingSource}
        onSubmit={async (data) => {
          setCreatingSource(true);
          try {
            await createSyncSource(data);
            setWizardOpen(false);
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
    </FileDropZone>
  );
}
