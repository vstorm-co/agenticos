"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuth } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import {
  Button,
  Input,
  Badge,
  Skeleton,
  Spinner,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui";
import {
  Database,
  Search,
  Trash2,
  FileText,
  Plus,
  Upload,
  CheckCircle,
  XCircle,
  Eye,
  RefreshCw,
} from "lucide-react";
import {
  listCollections,
  getCollectionInfo,
  createCollection,
  deleteCollection,
  listTrackedDocuments,
  deleteTrackedDocument,
  ingestFile,
  searchDocuments,
  openTrackedDocument,
  listSyncLogs,
  cancelSync,
  listSyncSources,
  createSyncSource,
  deleteSyncSource,
  triggerSyncSource,
  listConnectors,
  type RAGCollectionInfo,
  type RAGTrackedDocument,
  type RAGSearchResult,
  type SyncSourceCreate,
} from "@/lib/rag-api";
import { DragDropOverlay } from "@/components/rag/drag-drop-overlay";
import { SyncSourceWizard } from "@/components/rag/sync-source-wizard";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { ErrorState } from "@/components/states";
import { useChanged } from "@/hooks/use-changed";
import { useOrgStore } from "@/stores";
import { PageHeader } from "@/components/dashboard/page-header";
import { usePollWhileIngesting } from "@/hooks";

import { getErrorMessage, isAppAdmin, MAX_UPLOAD_SIZE_MB, timeAgo } from "@/lib/utils";
import { useTranslations } from "next-intl";

interface CollectionWithInfo {
  name: string;
  info: RAGCollectionInfo | null;
}

function StatusIcon({ status }: { status: string }) {
  const label = status === "done" ? "Completed" : status === "error" ? "Failed" : "Processing";
  return (
    <span role="status" aria-label={label}>
      {status === "done" && <CheckCircle className="text-foreground h-4 w-4" />}
      {status === "error" && <XCircle className="text-destructive h-4 w-4" />}
      {status !== "done" && status !== "error" && (
        <Spinner className="text-muted-foreground h-4 w-4" />
      )}
    </span>
  );
}

/**
 * Whether the organization the caller started in is still the active one.
 *
 * Clearing this page's state as the organization changes is not enough on its
 * own: a request in flight across the switch resolves afterwards and writes the
 * previous tenant's rows straight back into the state that was just emptied.
 * Every imperative fetch below checks before it writes. Read from the store
 * rather than from a render, so the fetchers that call it can stay stable.
 */
function stillCurrent(startedIn: string): boolean {
  return (useOrgStore.getState().activeOrgId ?? "") === startedIn;
}

const DEFAULT_FORMATS = [".pdf", ".docx", ".txt", ".md"];

export default function RAGPage() {
  const t = useTranslations("pages.rag");
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (user && !isAppAdmin(user)) {
      router.replace(ROUTES.CHAT);
    }
  }, [user, router]);

  // The collection the user picked, falling back to the first one the server
  // returned. Derived rather than written back after the fetch: the effect that
  // did that ran a second render pass, and it could only default once - a
  // collection list arriving after a failed first load left the page with
  // nothing selected and no way to notice.
  const queryClient = useQueryClient();
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const [chosen, setChosen] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<RAGSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{
    current: number;
    total: number;
    filename: string;
  } | null>(null);
  const [newName, setNewName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [tab, setTabState] = useState<"documents" | "search" | "sync">(() => {
    if (typeof window !== "undefined") {
      const t = new URLSearchParams(window.location.search).get("tab");
      if (t === "search" || t === "sync") return t;
    }
    return "documents";
  });
  const setTab = (t: "documents" | "search" | "sync") => {
    setTabState(t);
    const url = new URL(window.location.href);
    if (t === "documents") url.searchParams.delete("tab");
    else url.searchParams.set("tab", t);
    window.history.replaceState({}, "", url.toString());
  };
  const [addSourceOpen, setAddSourceOpen] = useState(false);
  const [addSourceSubmitting, setAddSourceSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Server data through the query layer, which is where `.claude/rules/frontend.md`
  // says it lives. Both fetchers set their loading flag synchronously before
  // the first await, so an effect calling either of them wrote state during the
  // effect and forced a cascading render.
  const {
    data: collections = [],
    isPending: loading,
    refetch: refetchCollections,
  } = useQuery({
    queryKey: qk.rag.collections(orgId),
    // One toast, so the failure is visible on a page whose empty state cannot
    // tell "no collections" from "the request failed" - and no retry, so it
    // stays one.
    retry: false,
    queryFn: async (): Promise<CollectionWithInfo[]> => {
      try {
        const data = await listCollections();
        const items: CollectionWithInfo[] = [];
        for (const name of data.items) {
          try {
            items.push({ name, info: await getCollectionInfo(name) });
          } catch {
            items.push({ name, info: null });
          }
        }
        return items;
      } catch (err) {
        toast.error(t("failedLoadCollections"));
        throw err;
      }
    },
  });

  const selected = chosen || collections[0]?.name || "";

  // The collection the user picked does not exist in the next organization, and
  // neither do the results of a search inside it. Everything else the page
  // holds is a query keyed on the organization, so it answers for itself.
  if (useChanged(orgId)) {
    setChosen("");
    setSearchResults([]);
    setSearchDone(false);
  }

  const {
    data: docs = [],
    isPending: docsPending,
    error: docsError,
    refetch: refetchDocs,
  } = useQuery({
    queryKey: qk.rag.documents(orgId, selected),
    queryFn: () => listTrackedDocuments(selected).then((d) => d.items || []),
    enabled: Boolean(selected),
  });
  const docsLoading = Boolean(selected) && docsPending;

  const { data: supportedFormats = DEFAULT_FORMATS } = useQuery({
    queryKey: qk.rag.supportedFormats(),
    queryFn: () => apiClient.get<{ formats: string[] }>("/rag/supported-formats"),
    select: (data) => data.formats,
  });

  // The sync tab, through the query layer like everything else on this page.
  // These were three imperative fetchers writing their own loading flags before
  // their first await, loaded from the tab's `onClick` alone - so switching
  // organization while already on the tab left all three lists showing the
  // previous tenant's rows, and clearing them left the tab blank until the user
  // clicked away and back. Keyed on the organization and enabled by the tab,
  // both answer themselves.
  const syncEnabled = tab === "sync";

  const { data: syncSources = [], isPending: syncSourcesPending } = useQuery({
    queryKey: qk.rag.syncSources(orgId),
    queryFn: () => listSyncSources().then((d) => d.items || []),
    enabled: syncEnabled,
  });
  const syncSourcesLoading = syncEnabled && syncSourcesPending;

  const { data: syncLogs = [], isPending: syncLogsPending } = useQuery({
    queryKey: qk.rag.syncLogs(orgId, selected),
    queryFn: () => listSyncLogs(selected || undefined).then((d) => d.items || []),
    enabled: syncEnabled,
  });
  const syncLogsLoading = syncEnabled && syncLogsPending;

  const { data: connectors = [] } = useQuery({
    queryKey: qk.rag.connectors(orgId),
    queryFn: () => listConnectors().then((d) => d.items || []),
    enabled: syncEnabled,
  });

  const refreshSync = () => void queryClient.invalidateQueries({ queryKey: qk.rag.sync(orgId) });

  const handleAddSource = async (data: SyncSourceCreate) => {
    if (!data.name || !data.connector_type || !data.collection_name) {
      toast.error(t("nameConnectorTypeCollection"));
      return;
    }
    setAddSourceSubmitting(true);
    try {
      await createSyncSource(data);
      toast.success(`Source "${data.name}" created`);
      setAddSourceOpen(false);
      refreshSync();
    } catch (err) {
      toast.error(getErrorMessage(err, t("failedCreateSource")));
    } finally {
      setAddSourceSubmitting(false);
    }
  };

  const handleDeleteSource = async (sourceId: string) => {
    try {
      await deleteSyncSource(sourceId);
      toast.success(t("sourceDeleted"));
      refreshSync();
    } catch {
      toast.error(t("failedDeleteSource"));
    }
  };

  const handleTriggerSync = async (sourceId: string) => {
    try {
      await triggerSyncSource(sourceId);
      toast.success(t("syncTriggered"));
      refreshSync();
    } catch {
      toast.error(t("failedTriggerSync"));
    }
  };

  usePollWhileIngesting(docs, () => void refetchDocs());

  // A finished ingest changes the collection's vector count, so refresh the
  // sidebar once the last document settles rather than on every poll tick.
  const wasIngestingRef = useRef(false);
  useEffect(() => {
    const ingesting = docs.some((d) => d.status === "processing");
    if (wasIngestingRef.current && !ingesting) void refetchCollections();
    wasIngestingRef.current = ingesting;
  }, [docs, refetchCollections]);

  const handleCreate = async () => {
    const name = newName.trim().toLowerCase().replace(/\s+/g, "_");
    if (!name) return;
    const startedIn = orgId;
    try {
      await createCollection(name);
      toast.success(`"${name}" created`);
      setNewName("");
      setShowCreate(false);
      // The collection was created in the organization the request started in;
      // selecting it after a switch would point the page at a collection the
      // active tenant does not have.
      if (!stillCurrent(startedIn)) return;
      await refetchCollections();
      if (stillCurrent(startedIn)) setChosen(name);
    } catch {
      toast.error(t("failedCreateCollection"));
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await deleteCollection(name);
      toast.success(`"${name}" deleted`);
      queryClient.setQueryData<CollectionWithInfo[]>(qk.rag.collections(orgId), (prev = []) =>
        prev.filter((c) => c.name !== name),
      );
      if (selected === name) {
        setChosen("");
        queryClient.removeQueries({ queryKey: qk.rag.documents(orgId, name) });
        setSearchResults([]);
      }
    } catch {
      toast.error(t("failedDelete"));
    }
  };

  const handleDeleteDoc = async (docId: string) => {
    try {
      await deleteTrackedDocument(docId);
      toast.success(t("documentDeleted"));
      queryClient.setQueryData<RAGTrackedDocument[]>(
        qk.rag.documents(orgId, selected),
        (prev = []) => prev.filter((d) => d.id !== docId),
      );
      void refetchCollections();
    } catch {
      toast.error(t("failedDelete2"));
    }
  };

  const processFiles = useCallback(
    async (fileList: File[]) => {
      if (!selected || fileList.length === 0) return;
      const startedIn = orgId;
      const allowedExts = supportedFormats.map((f) => f.toLowerCase());
      let successCount = 0;
      let errorCount = 0;

      setUploading(true);
      for (let i = 0; i < fileList.length; i++) {
        const file: File | undefined = fileList[i];
        if (!file) continue;
        setUploadProgress({ current: i + 1, total: fileList.length, filename: file.name });

        const ext = "." + (file.name.split(".").pop()?.toLowerCase() ?? "");
        if (allowedExts.length > 0 && !allowedExts.includes(ext)) {
          toast.error(t("unsupportedFormat", { file: file.name, ext }));
          errorCount++;
          continue;
        }
        if (file.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024) {
          toast.error(t("fileTooLarge", { file: file.name, max: MAX_UPLOAD_SIZE_MB }));
          errorCount++;
          continue;
        }

        // Each upload reads the organization as it goes out, so a switch part
        // way through a batch would write the rest of the files into the new
        // tenant. Stopping is the only honest answer: the remaining files were
        // chosen for a collection this tenant does not have.
        if (!stillCurrent(startedIn)) {
          toast.error(t("uploadStoppedOrganizationChanged"));
          break;
        }

        try {
          await ingestFile(selected, file);
          successCount++;
        } catch (err) {
          toast.error(`${file.name}: ${getErrorMessage(err, t("failed"))}`);
          errorCount++;
        }
      }

      setUploading(false);
      setUploadProgress(null);

      if (successCount > 0) {
        toast.success(
          errorCount > 0
            ? t("ingestedWithFailures", { count: successCount, failed: errorCount })
            : t("ingested", { count: successCount }),
        );
      }

      await refetchDocs();
      await refetchCollections();
    },
    [selected, supportedFormats, refetchDocs, refetchCollections, orgId, t],
  );

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    e.target.value = "";
    await processFiles(Array.from(files));
  };

  const handleDrop = useCallback(
    (files: File[]) => {
      if (!selected) {
        toast.error(t("selectCollectionBeforeDropping"));
        return;
      }
      processFiles(files);
    },
    [selected, processFiles, t],
  );

  /** Open a document's original file, reporting a refusal rather than a blank tab. */
  const openOriginal = async (docId: string) => {
    try {
      await openTrackedDocument(docId);
    } catch (err) {
      toast.error(getErrorMessage(err, t("couldNotOpenOriginal")));
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim() || !selected) return;
    const startedIn = orgId;
    setSearching(true);
    try {
      const data = await searchDocuments({
        query: searchQuery,
        collection_name: selected,
        limit: 10,
      });
      if (!stillCurrent(startedIn)) return;
      setSearchResults(data.results);
      setSearchDone(true);
    } catch {
      toast.error(t("searchFailed"));
    } finally {
      setSearching(false);
    }
  };

  const info = collections.find((c) => c.name === selected)?.info;

  const tabs: { key: "documents" | "search" | "sync"; label: string }[] = [
    { key: "documents", label: docs.length > 0 ? `Documents (${docs.length})` : t("documents") },
    { key: "search", label: t("search") },
    { key: "sync", label: t("sync") },
  ];

  return (
    <div className="space-y-6">
      <DragDropOverlay
        onDrop={handleDrop}
        disabled={!selected || uploading}
        title={selected ? t("dropFilesInto", { collection: selected }) : t("dropFilesUpload")}
        description={selected ? t("filesWillBeIngested") : t("selectCollectionFirst")}
        acceptedFormats={supportedFormats}
      />
      <SyncSourceWizard
        open={addSourceOpen}
        onOpenChange={setAddSourceOpen}
        connectors={connectors}
        collections={collections.map((c) => ({ name: c.name }))}
        defaultCollection={selected}
        onSubmit={handleAddSource}
        submitting={addSourceSubmitting}
      />

      <PageHeader title={t("rag")} description={t("manageKnowledgeBaseCollections")} />

      <div className="border-border bg-card rounded-xl border p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-1 flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Database className="text-muted-foreground h-4 w-4 shrink-0" />
              <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                {t("collection")}
              </span>
            </div>
            {loading ? (
              <Skeleton className="h-9 w-56 rounded-xl" />
            ) : collections.length === 0 ? (
              <span className="text-muted-foreground text-sm">{t("noCollectionsYet")}</span>
            ) : (
              <Select
                value={selected}
                onValueChange={(v) => {
                  setChosen(v);
                  setSearchResults([]);
                  setSearchDone(false);
                  setTab("documents");
                }}
              >
                <SelectTrigger className="h-9 w-full rounded-xl sm:w-72">
                  <SelectValue placeholder={t("selectCollection")} />
                </SelectTrigger>
                <SelectContent>
                  {collections.map((col) => (
                    <SelectItem key={col.name} value={col.name}>
                      {col.name}
                      {col.info ? ` · ${col.info.total_vectors.toLocaleString()} vectors` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {info && (
              <span className="text-muted-foreground font-mono text-xs">
                {info.total_vectors.toLocaleString()} vectors · {info.dim}d
              </span>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="rounded-xl"
              onClick={() => setShowCreate((v) => !v)}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              {t("newCollection")}
            </Button>
            {uploadProgress ? (
              <div
                className="text-muted-foreground flex items-center gap-2 text-xs"
                role="status"
                aria-live="polite"
              >
                <Spinner className="text-muted-foreground h-3.5 w-3.5" aria-hidden="true" />
                <span className="font-mono">
                  {uploadProgress.current}/{uploadProgress.total}
                </span>
                <span className="max-w-[120px] truncate">{uploadProgress.filename}</span>
              </div>
            ) : (
              <Button
                size="sm"
                variant="outline"
                className="rounded-xl"
                onClick={() => fileRef.current?.click()}
                disabled={uploading || !selected}
              >
                <Upload className="mr-1.5 h-3.5 w-3.5" />
                {t("uploadFiles")}
              </Button>
            )}
            {selected && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-destructive hover:text-destructive rounded-xl"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>
                      {t("deleteCollectionNamed", { name: selected })}
                    </AlertDialogTitle>
                    <AlertDialogDescription>{t("allDocumentsVectorsWill")}</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
                    <AlertDialogAction
                      className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      onClick={() => handleDelete(selected)}
                    >
                      {t("delete")}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
            <input
              ref={fileRef}
              type="file"
              onChange={handleUpload}
              accept={supportedFormats.join(",")}
              multiple
              className="hidden"
            />
          </div>
        </div>

        {showCreate && (
          <div className="border-border mt-3 flex gap-2 border-t pt-3">
            <Input
              placeholder={t("collectionName")}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === t("enter4") && handleCreate()}
              className="h-9 max-w-xs rounded-xl"
            />
            <Button size="sm" className="h-9 rounded-xl" onClick={handleCreate}>
              {t("create")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-9 rounded-xl"
              onClick={() => {
                setShowCreate(false);
                setNewName("");
              }}
            >
              {t("cancel")}
            </Button>
          </div>
        )}

        {uploadProgress && (
          <div className="mt-3">
            <div className="bg-muted h-1 w-full overflow-hidden rounded-full">
              <div
                className="bg-foreground h-full rounded-full transition-all"
                style={{ width: `${(uploadProgress.current / uploadProgress.total) * 100}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {!selected ? (
        <div className="border-border bg-card text-muted-foreground flex flex-col items-center justify-center rounded-xl border py-16 text-center">
          <Database className="mb-3 h-8 w-8" />
          <p className="text-sm">{t("selectCreateCollectionGet")}</p>
        </div>
      ) : (
        <>
          <div className="border-border flex gap-1 border-b">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  tab === t.key
                    ? "border-foreground text-foreground"
                    : "text-muted-foreground hover:text-foreground border-transparent"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "documents" &&
            (docsLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-16 w-full rounded-xl" />
                ))}
              </div>
            ) : docsError ? (
              // Not the empty state: "this collection holds nothing" and "the
              // request answered 502" are the same pixels, and only one of them
              // is worth offering an upload button for.
              <ErrorState
                title={t("couldnTLoadDocuments")}
                description={getErrorMessage(docsError, t("documentListRequestFailed"))}
                cta={{ label: t("tryAgain3"), onClick: () => void refetchDocs() }}
              />
            ) : docs.length === 0 ? (
              <div className="border-border bg-card flex flex-col items-center justify-center rounded-xl border py-16 text-center">
                <FileText className="text-muted-foreground mb-3 h-8 w-8" />
                <p className="text-foreground text-sm font-medium">{t("noDocuments")}</p>
                <p className="text-muted-foreground mt-1 text-xs">{t("uploadPdfDocxTxt")}</p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4 rounded-xl"
                  onClick={() => fileRef.current?.click()}
                >
                  <Upload className="mr-2 h-4 w-4" />
                  {t("uploadFiles2")}
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {docs.map((doc) => (
                  <div
                    key={doc.id}
                    className="border-border bg-card hover:bg-accent flex items-center justify-between rounded-xl border p-3 transition-colors"
                  >
                    <div className="flex items-center gap-3 overflow-hidden">
                      <StatusIcon status={doc.status} />
                      <div className="min-w-0">
                        <p className="text-foreground truncate text-sm font-medium">
                          {doc.filename}
                        </p>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="font-mono text-[10px]">
                            {doc.filetype.toUpperCase()}
                          </Badge>
                          {doc.status === "done" && (
                            <span className="text-muted-foreground font-mono text-xs">
                              {(doc.filesize / 1024).toFixed(0)} KB
                            </span>
                          )}
                          {doc.status === "processing" && (
                            <span className="text-muted-foreground text-xs">{t("processing")}</span>
                          )}
                          {doc.status === "error" && (
                            <span className="text-destructive max-w-[200px] truncate text-xs">
                              {doc.error_message}
                            </span>
                          )}
                          {doc.created_at && (
                            <span className="text-muted-foreground text-[10px]">
                              {new Date(doc.created_at).toLocaleDateString()}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-0.5">
                      {doc.has_file && (
                        <button
                          type="button"
                          onClick={() => void openOriginal(doc.id)}
                          className="text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg p-1.5 transition-colors"
                          title={t("viewOriginal")}
                        >
                          <Eye className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <button className="text-destructive hover:bg-accent rounded-lg p-1.5 transition-colors">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>
                              Delete &ldquo;{doc.filename}&rdquo;?
                            </AlertDialogTitle>
                            <AlertDialogDescription>
                              {t("willRemoveDocumentFrom")}
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>{t("cancel2")}</AlertDialogCancel>
                            <AlertDialogAction
                              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                              onClick={() => handleDeleteDoc(doc.id)}
                            >
                              {t("delete2")}
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>
                ))}
              </div>
            ))}

          {tab === "search" && (
            <div className="space-y-4">
              <div className="border-border bg-card rounded-xl border p-4">
                <div className="flex gap-2">
                  <Input
                    placeholder={t("searchInCollection", { collection: selected })}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === t("enter5") && handleSearch()}
                    className="rounded-xl"
                  />
                  <Button
                    onClick={handleSearch}
                    disabled={searching || !searchQuery.trim()}
                    className="rounded-xl"
                  >
                    <Search className="mr-2 h-4 w-4" />
                    {searching ? "..." : t("search2")}
                  </Button>
                </div>
              </div>

              {searchDone && searchResults.length === 0 && !searching && (
                <div className="border-border bg-card flex flex-col items-center justify-center rounded-xl border py-12 text-center">
                  <Search className="text-muted-foreground mb-3 h-8 w-8" />
                  <p className="text-foreground text-sm font-medium">{t("noResultsFound")}</p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {t("tryDifferentQueryCheck")}
                  </p>
                </div>
              )}

              {searchResults.length > 0 && (
                <div className="space-y-2">
                  {searchResults.map((r, i) => {
                    // Try to find the source document for "View source" link
                    const sourceDoc = docs.find(
                      (d) => d.filename === r.metadata?.filename && d.has_file,
                    );
                    return (
                      <div
                        key={i}
                        className="border-border bg-card rounded-xl border p-4 transition-colors"
                      >
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                          <FileText className="text-muted-foreground h-3.5 w-3.5" />
                          <span className="text-foreground text-xs font-medium">
                            {String(r.metadata?.filename ?? "?")}
                          </span>
                          {r.metadata?.page_num != null && (
                            <Badge variant="outline" className="font-mono text-[10px]">
                              p.{String(r.metadata.page_num)}
                            </Badge>
                          )}
                          <Badge variant="secondary" className="ml-auto font-mono text-[10px]">
                            {r.score.toFixed(3)}
                          </Badge>
                          {sourceDoc && (
                            <button
                              type="button"
                              onClick={() => void openOriginal(sourceDoc.id)}
                              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-[10px] font-medium"
                            >
                              <Eye className="h-3 w-3" />
                              {t("viewSource")}
                            </button>
                          )}
                        </div>
                        <p className="text-muted-foreground text-sm leading-relaxed">{r.content}</p>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {tab === "sync" && (
            <div className="space-y-6">
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-foreground text-sm font-semibold">{t("syncSources")}</h3>
                  <Button
                    size="sm"
                    variant="outline"
                    className="rounded-xl"
                    onClick={() => {
                      setAddSourceOpen(true);
                    }}
                  >
                    <Plus className="mr-1 h-3.5 w-3.5" />
                    {t("addSource")}
                  </Button>
                </div>

                {syncSourcesLoading ? (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <Skeleton key={i} className="h-28 w-full rounded-xl" />
                    ))}
                  </div>
                ) : syncSources.length === 0 ? (
                  <div className="border-border bg-card flex flex-col items-center justify-center rounded-xl border py-8 text-center">
                    <Database className="text-muted-foreground mb-2 h-6 w-6" />
                    <p className="text-foreground text-sm font-medium">
                      {t("noSyncSourcesConfigured")}
                    </p>
                    <p className="text-muted-foreground mt-1 text-xs">
                      {t("addSourceStartSyncing")}
                    </p>
                  </div>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {syncSources.map((source) => (
                      <div key={source.id} className="border-border bg-card rounded-xl border p-4">
                        <div className="mb-2 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Database className="text-muted-foreground h-4 w-4" />
                            <span className="text-foreground text-sm font-medium">
                              {source.name}
                            </span>
                          </div>
                          <Badge variant={source.is_active ? "default" : "secondary"}>
                            {source.is_active ? t("active") : t("disabled")}
                          </Badge>
                        </div>
                        <div className="text-muted-foreground space-y-1 text-sm">
                          <p>
                            {source.connector_type} &rarr; {source.collection_name}
                          </p>
                          <p>
                            {source.schedule_minutes
                              ? `Every ${source.schedule_minutes}min`
                              : t("manual")}{" "}
                            &bull; {source.sync_mode}
                          </p>
                          {source.last_sync_at && (
                            <p className="text-xs">
                              Last sync: {timeAgo(source.last_sync_at)} &mdash;{" "}
                              {source.last_sync_status}
                            </p>
                          )}
                          {source.last_error && (
                            <p className="text-destructive truncate text-xs">{source.last_error}</p>
                          )}
                        </div>
                        <div className="mt-3 flex gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            className="rounded-xl"
                            onClick={() => handleTriggerSync(source.id)}
                          >
                            <RefreshCw className="mr-1 h-3 w-3" />
                            {t("syncNow")}
                          </Button>
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="text-destructive hover:text-destructive rounded-xl"
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>
                                  Delete source &ldquo;{source.name}&rdquo;?
                                </AlertDialogTitle>
                                <AlertDialogDescription>
                                  {t("willRemoveSyncSource")}
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>{t("cancel3")}</AlertDialogCancel>
                                <AlertDialogAction
                                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                  onClick={() => handleDeleteSource(source.id)}
                                >
                                  {t("delete3")}
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <h3 className="text-foreground mb-3 text-sm font-semibold">{t("history")}</h3>
                {syncLogsLoading ? (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <Skeleton key={i} className="h-16 w-full rounded-xl" />
                    ))}
                  </div>
                ) : syncLogs.length === 0 ? (
                  <p className="text-muted-foreground text-sm">{t("noSyncHistoryYet")}</p>
                ) : (
                  <div className="space-y-2">
                    {syncLogs.map((log) => (
                      <div key={log.id} className="border-border bg-card rounded-xl border p-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <StatusIcon
                              status={log.status === "running" ? "processing" : log.status}
                            />
                            <span className="text-foreground text-sm font-medium">
                              {log.collection_name}
                            </span>
                            <Badge variant="outline" className="font-mono text-[10px]">
                              {log.source}
                            </Badge>
                            <Badge variant="secondary" className="font-mono text-[10px]">
                              {log.mode}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-2">
                            {log.started_at && (
                              <span className="text-muted-foreground font-mono text-[10px]">
                                {new Date(log.started_at).toLocaleString()}
                              </span>
                            )}
                            {log.status === "running" && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-destructive h-6 rounded-lg px-2 text-[10px]"
                                onClick={async () => {
                                  try {
                                    await cancelSync(log.id);
                                    toast.success(t("syncCancelled"));
                                    refreshSync();
                                  } catch {
                                    toast.error(t("failedCancel"));
                                  }
                                }}
                              >
                                {t("cancel2")}
                              </Button>
                            )}
                          </div>
                        </div>
                        <div className="text-muted-foreground mt-2 flex flex-wrap gap-3 font-mono text-xs">
                          <span>{log.total_files} total</span>
                          {log.ingested > 0 && (
                            <span className="text-foreground">{log.ingested} new</span>
                          )}
                          {log.updated > 0 && (
                            <span className="text-foreground">{log.updated} updated</span>
                          )}
                          {log.skipped > 0 && <span>{log.skipped} skipped</span>}
                          {log.failed > 0 && (
                            <span className="text-destructive">{log.failed} failed</span>
                          )}
                        </div>
                        {log.error_message && (
                          <p className="text-destructive mt-1 truncate text-xs">
                            {log.error_message}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
