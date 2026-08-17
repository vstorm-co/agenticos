import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useKBDetail, useKnowledgeBases } from "./use-knowledge-bases";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { KnowledgeBase } from "@/types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** Hoisted so a test can read the cache directly, which is where the leak is. */
let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function document(id: string) {
  return { id, filename: `${id}.pdf`, status: "done" };
}

/**
 * What each of the KB detail page's five parallel reads answers with.
 *
 * Three of them are allowed to fail without failing the page - sync sources,
 * org integrations and connectors are behind their own permissions - so the
 * routes are matched rather than mocked in order.
 */
function serveDetail({
  documents = [document("d-1")],
  documentsTotal = 1,
  sources = [{ id: "s-1", name: "Drive" }],
  integrations = [{ id: "s-org", name: "Shared Drive" }],
  connectors = [{ type: "gdrive" }],
}: {
  documents?: unknown[];
  documentsTotal?: number;
  sources?: unknown[] | Error;
  integrations?: unknown[] | Error;
  connectors?: unknown[] | Error;
} = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/documents")) return { items: documents, total: documentsTotal };
    if (path.endsWith("/sync-sources")) {
      if (sources instanceof Error) throw sources;
      return { items: sources, total: sources.length };
    }
    if (path.endsWith("/org-integrations")) {
      if (integrations instanceof Error) throw integrations;
      return { items: integrations, total: integrations.length };
    }
    if (path.endsWith("/connectors")) {
      if (connectors instanceof Error) throw connectors;
      return { items: connectors };
    }
    return { id: "kb-1", name: "Handbook", ingestion_config: DEFAULT_INGESTION_CONFIG };
  });
}

/** A fake `XMLHttpRequest`, since the upload reads byte-level progress off one. */
interface FakeXhr {
  open: ReturnType<typeof vi.fn>;
  setRequestHeader: ReturnType<typeof vi.fn>;
  send: ReturnType<typeof vi.fn>;
  withCredentials: boolean;
  status: number;
  responseText: string;
  upload: { onprogress?: (event: ProgressEvent) => void; onload?: () => void };
  onload?: () => void;
  onerror?: () => void;
}

/** One entry per upload started, in order: a file can be uploaded twice at once. */
let xhrs: FakeXhr[];

/** The request the upload under test is using. */
function xhr(index = 0): FakeXhr {
  return xhrs[index]!;
}

function stubXhr() {
  xhrs = [];
  // A class, not `vi.fn(() => ({...}))`: the code under test calls
  // `new XMLHttpRequest()`, and an arrow function cannot be constructed - the
  // fake returned nothing, so no request was ever recorded.
  class FakeXhrImpl implements FakeXhr {
    open = vi.fn();
    send = vi.fn();
    setRequestHeader = vi.fn();
    withCredentials = false;
    status = 201;
    responseText = "{}";
    upload: FakeXhr["upload"] = {};

    constructor() {
      xhrs.push(this);
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXhrImpl);
}

/** Wait until the upload has actually been sent, so its handlers exist. */
async function sent(index = 0) {
  await waitFor(() => expect(xhrs[index]?.send).toHaveBeenCalled());
  return xhr(index);
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  // Seeded rather than fetched: both hooks resolve the tenant through the
  // organizations query now, and several of these tests assert on exactly
  // which requests went out.
  client.setQueryData(qk.organizations.list(), []);
  // The hook reads it, and a test that leaves one behind hands the next one an
  // organization it never chose - which, for the two switch tests below, is the
  // difference between asserting something and asserting nothing.
  useOrgStore.setState({ activeOrgId: null });
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "x" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "kb-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
  stubXhr();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the list of knowledge bases", () => {
  it("reads the collections this organization has", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "kb-1" }], total: 1 });

    const { result } = renderHook(() => useKnowledgeBases(), { wrapper });

    await waitFor(() => expect(result.current.kbs).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/kb");
  });

  it("keeps a collection created in one organization out of another's list", async () => {
    // `qk.kb.list()` names no tenant, and `setQueryData` recreates a key the
    // switch had just dropped - so a creation that finished late put the
    // previous organization's collection into the list the new one is reading.
    useOrgStore.setState({ activeOrgId: "org-a" });
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useKnowledgeBases(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.post).mockImplementation(
      () => new Promise((resolve) => (answer = resolve)),
    );
    let creating: Promise<unknown>;
    await act(async () => {
      creating = result.current.createKB({ name: "Org A's handbook", scope: "org" });
      await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    });

    await act(async () => {
      useOrgStore.setState({ activeOrgId: "org-b" });
      answer({ id: "kb-private", name: "Org A's handbook" });
      await creating!;
    });

    // Read from the cache, not from the hook: the leak is a key being written,
    // and a render that has not flushed yet would report it absent either way.
    const cached = client.getQueryData<Array<{ id: string }>>(["kb", "list"]) ?? [];
    expect(cached.map((kb) => kb.id)).not.toContain("kb-private");
  });

  it("lets a refused creation through, because the dialog has fields to blame", async () => {
    // A name already taken belongs beside the name field.
    vi.mocked(apiClient.post).mockRejectedValue(new Error("That name is taken"));
    const { result } = renderHook(() => useKnowledgeBases(), { wrapper });

    await expect(result.current.createKB({ name: "Handbook", scope: "org" })).rejects.toThrow(
      "That name is taken",
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("creates a collection and says so", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "kb-2", name: "Contracts" });
    const { result } = renderHook(() => useKnowledgeBases(), { wrapper });

    const created = await result.current.createKB({ name: "Contracts", scope: "org" });

    expect(created).toMatchObject({ id: "kb-2" });
    expect(apiClient.post).toHaveBeenCalledWith("/kb", { name: "Contracts", scope: "org" });
    expect(toast.success).toHaveBeenCalledWith("Knowledge base created");
  });

  it("renames a collection, and raises a refusal for the dialog to place", async () => {
    // A rename is driven from a dialog that owns the name field, so a refusal is
    // rethrown rather than toasted here - a name already taken belongs beside
    // that field, like createKB and updateIngestion.
    const { result } = renderHook(() => useKnowledgeBases(), { wrapper });

    await act(async () => {
      await result.current.patchKB("kb-1", { name: "Handbook v2" });
    });
    expect(apiClient.patch).toHaveBeenCalledWith("/kb/kb-1", { name: "Handbook v2" });
    expect(toast.success).toHaveBeenCalledWith("Knowledge base updated");

    vi.mocked(apiClient.patch).mockRejectedValue(new Error("That name is taken"));
    await expect(result.current.patchKB("kb-1", { name: "x" })).rejects.toThrow(
      "That name is taken",
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("puts the renamed collection back in the list, not just a toast", async () => {
    // The toast says it worked; the cache is what the page renders. These were
    // asserted separately from each other until the list was seeded, at which
    // point the rewrite is observable.
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        { id: "kb-1", name: "Handbook" },
        { id: "kb-2", name: "Contracts" },
      ],
      total: 2,
    });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "kb-1", name: "Handbook v2" });
    const { result } = renderHook(() => useKnowledgeBases(), { wrapper });
    await waitFor(() => expect(result.current.kbs).toHaveLength(2));

    await act(async () => {
      await result.current.patchKB("kb-1", { name: "Handbook v2" });
    });

    await waitFor(() =>
      expect(result.current.kbs.map((kb) => kb.name)).toEqual(["Handbook v2", "Contracts"]),
    );
  });

  it("refetches on demand", async () => {
    const { result } = renderHook(() => useKnowledgeBases(), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));

    await act(async () => {
      result.current.fetchKBs();
    });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });
});

/**
 * One collection's page: the collection, its documents, and the sync sources
 * feeding it.
 *
 * Five reads in parallel, and three of them are allowed to fail. Sync sources,
 * org integrations and connectors each sit behind their own permission, so a
 * member who can read the collection but not manage integrations has to get the
 * page rather than an error - which is why those three swallow and the first two
 * do not.
 *
 * Uploads go through `XMLHttpRequest` rather than `fetch`, because that is the
 * only way to read byte-level progress, and the refusal handling is hand-rolled
 * as a result: the backend answers `{"error": {...}}` and this once looked for
 * `detail`, so every reason an upload can be refused arrived as "Upload failed".
 */
describe("one collection's page", () => {
  it("reads nothing until a collection is open", async () => {
    const { result } = renderHook(() => useKBDetail(null), { wrapper });

    await act(async () => {
      await result.current.refresh();
    });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("lets no deletion finished after the switch touch the next organization", async () => {
    // Both are filters, so neither can show the previous tenant's rows - but
    // the document one also decrements a total, and decrementing the count of
    // a list belonging to somebody else is the same mistake wearing a number.
    for (const remove of ["document", "sync source"] as const) {
      client.clear();
      useOrgStore.setState({ activeOrgId: "org-a" });
      serveDetail({ documents: [document("d-1")], documentsTotal: 7 });
      const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
      await waitFor(() => expect(result.current.documentsTotal).toBe(7));

      let answer: () => void = () => {};
      vi.mocked(apiClient.delete).mockImplementation(
        () => new Promise((resolve) => (answer = () => resolve(undefined))),
      );
      let removing: Promise<void>;
      await act(async () => {
        removing =
          remove === "document"
            ? result.current.deleteDocument("d-1")
            : result.current.deleteSyncSource("s-1");
        await waitFor(() => expect(apiClient.delete).toHaveBeenCalled());
      });

      await act(async () => {
        useOrgStore.setState({ activeOrgId: "org-b" });
        answer();
        await removing!;
      });

      expect(toast.success).not.toHaveBeenCalledWith("Document removed");
      expect(toast.success).not.toHaveBeenCalledWith("Sync source removed");
      vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    }
  });

  it("keeps a save that finished late off the next organization's page", async () => {
    // Save the ingestion settings, close the dialog, switch before the PATCH
    // returns. The caller still gets its row - it asked, and the save happened
    // - but it is never written into the cache the next organization reads: the
    // guard drops the write, so the collection under `qk.kb.detail` is still the
    // one that was there, not the saved name from the tenant just left.
    useOrgStore.setState({ activeOrgId: "org-a" });
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.kb).toMatchObject({ name: "Handbook" }));

    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.patch).mockImplementation(
      () => new Promise((resolve) => (answer = resolve)),
    );
    let saving: Promise<unknown>;
    await act(async () => {
      saving = result.current.updateIngestion(DEFAULT_INGESTION_CONFIG);
      await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    });

    await act(async () => {
      useOrgStore.setState({ activeOrgId: "org-b" });
      answer({ id: "kb-1", name: "Org A's handbook" });
      await saving!;
    });

    expect(client.getQueryData<KnowledgeBase>(qk.kb.detail("kb-1"))?.name).toBe("Handbook");
    expect(toast.success).not.toHaveBeenCalledWith("Ingestion settings saved");
  });

  it("reads the collection, its documents and its sources together", async () => {
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await waitFor(() => expect(result.current.kb).toMatchObject({ id: "kb-1" }));
    expect(result.current.documents).toHaveLength(1);
    expect(result.current.syncSources).toHaveLength(1);
    expect(result.current.orgIntegrations).toHaveLength(1);
    expect(result.current.connectors).toHaveLength(1);
    expect(apiClient.get).toHaveBeenCalledWith("/kb/kb-1/documents?skip=0&limit=20");
  });

  it("still renders the page for somebody who may not read the integrations", async () => {
    // Three of the five reads are behind `connections:manage`. Failing the page on
    // them would hide a collection from the person who owns it.
    serveDetail({
      sources: new Error("403"),
      integrations: new Error("403"),
      connectors: new Error("403"),
    });
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await waitFor(() => expect(result.current.kb).toMatchObject({ id: "kb-1" }));

    expect(result.current.syncSources).toEqual([]);
    expect(result.current.error).toBeNull();
    expect(result.current.sectionFailures.syncSources).toBe(true);
  });

  it("says what went wrong when the collection itself cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Not your collection"));
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Not your collection"));
    expect(result.current.isLoading).toBe(false);
  });

  it("falls back to its own sentence for a failure that carries none", async () => {
    vi.mocked(apiClient.get).mockRejectedValue("boom");
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Failed to load knowledge base"));
  });

  it("says whether there are more documents than are on screen", async () => {
    serveDetail({ documents: [document("d-1")], documentsTotal: 40 });
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await waitFor(() => expect(result.current.documentsTotal).toBe(40));
    expect(result.current.hasMoreDocuments).toBe(true);
  });

  it("appends the next page rather than replacing the list", async () => {
    serveDetail({ documents: [document("d-1")], documentsTotal: 3 });
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toHaveLength(1));

    serveDetail({ documents: [document("d-2")], documentsTotal: 3 });
    await act(async () => {
      await result.current.loadMoreDocuments();
    });

    await waitFor(() =>
      expect(result.current.documents.map((doc) => doc.id)).toEqual(["d-1", "d-2"]),
    );
    expect(apiClient.get).toHaveBeenCalledWith("/kb/kb-1/documents?skip=1&limit=20");
  });

  it("does not list a document twice when a poll raced the append", async () => {
    serveDetail({ documents: [document("d-1")], documentsTotal: 2 });
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toHaveLength(1));

    // The next page comes back holding the same document a poll had already
    // re-read into the first - two pages, one id, and de-duplication is what
    // keeps it a list of one rather than the same row twice.
    await act(async () => {
      await result.current.loadMoreDocuments();
    });

    expect(result.current.documents.map((doc) => doc.id)).toEqual(["d-1"]);
  });

  it("re-reads every loaded page on refresh rather than collapsing the list", async () => {
    // A refresh that dropped an expanded list back to its first page would lose
    // the rest every time a poll fired. Each loaded page is re-read at its own
    // skip instead, so the expansion survives.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.includes("skip=0")) return { items: [document("d-0")], total: 300 };
      if (path.includes("skip=1")) return { items: [document("d-1")], total: 300 };
      if (path.includes("/documents")) return { items: [], total: 300 };
      return { id: "kb-1", name: "Handbook", ingestion_config: DEFAULT_INGESTION_CONFIG };
    });
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toHaveLength(1));
    await act(async () => {
      await result.current.loadMoreDocuments();
    });
    await waitFor(() => expect(result.current.documents).toHaveLength(2));

    vi.mocked(apiClient.get).mockClear();
    await act(async () => {
      await result.current.refresh();
    });

    expect(apiClient.get).toHaveBeenCalledWith("/kb/kb-1/documents?skip=0&limit=20");
    expect(apiClient.get).toHaveBeenCalledWith("/kb/kb-1/documents?skip=1&limit=20");
    expect(result.current.documents.map((doc) => doc.id)).toEqual(["d-0", "d-1"]);
  });

  it("reports a refused next page without emptying the list", async () => {
    serveDetail({ documents: [document("d-1")], documentsTotal: 3 });
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toHaveLength(1));

    vi.mocked(apiClient.get).mockRejectedValue(new Error("Gone"));
    await act(async () => {
      await result.current.loadMoreDocuments();
    });

    expect(toast.error).toHaveBeenCalledWith("Gone");
    expect(result.current.documents).toHaveLength(1);
    expect(result.current.isLoadingMoreDocs).toBe(false);
  });

  it("falls back to its own sentence for a next page that failed without one", async () => {
    serveDetail({ documents: [document("d-1")], documentsTotal: 3 });
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toHaveLength(1));

    vi.mocked(apiClient.get).mockRejectedValue("boom");
    await act(async () => {
      await result.current.loadMoreDocuments();
    });

    expect(toast.error).toHaveBeenCalledWith("Failed to load more documents");
  });

  it("loads no more documents when nothing is open", async () => {
    const { result } = renderHook(() => useKBDetail(null), { wrapper });

    await act(async () => {
      await result.current.loadMoreDocuments();
    });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("saves the parsing settings and keeps the collection it was handed back", async () => {
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.kb).toMatchObject({ id: "kb-1" }));
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "kb-1", name: "Handbook", ocr: true });

    await act(async () => {
      await result.current.updateIngestion(DEFAULT_INGESTION_CONFIG);
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/kb/kb-1", {
      ingestion_config: DEFAULT_INGESTION_CONFIG,
    });
    await waitFor(() => expect(result.current.kb).toMatchObject({ ocr: true }));
    expect(toast.success).toHaveBeenCalledWith("Ingestion settings saved");
  });

  it("refuses to save parsing settings with no collection open", async () => {
    // Rather than PATCHing `/kb/null`, which answers 404 and reads as a bug.
    const { result } = renderHook(() => useKBDetail(null), { wrapper });

    await expect(result.current.updateIngestion(DEFAULT_INGESTION_CONFIG)).rejects.toThrow(
      "No knowledge base is open",
    );
  });

  it("lets a refused parsing change through to the dialog that owns the fields", async () => {
    // The dialog decides which input a rejected chunk size belongs under.
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("chunk_overlap must be smaller"));

    await expect(result.current.updateIngestion(DEFAULT_INGESTION_CONFIG)).rejects.toThrow(
      "chunk_overlap must be smaller",
    );
  });

  it("drops a deleted document and the count with it", async () => {
    serveDetail({ documents: [document("d-1"), document("d-2")], documentsTotal: 2 });
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toHaveLength(2));

    await act(async () => {
      await result.current.deleteDocument("d-2");
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/kb/kb-1/documents/d-2");
    await waitFor(() => expect(result.current.documents.map((doc) => doc.id)).toEqual(["d-1"]));
    expect(result.current.documentsTotal).toBe(1);
  });

  it("reports a refused deletion", async () => {
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("Still indexing"));

    await act(async () => {
      await result.current.deleteDocument("d-1");
    });

    expect(toast.error).toHaveBeenCalledWith("Still indexing");
  });

  it("falls back to its own sentence for a deletion that failed without one", async () => {
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.delete).mockRejectedValue("boom");

    await act(async () => {
      await result.current.deleteDocument("d-1");
    });

    expect(toast.error).toHaveBeenCalledWith("Failed to delete document");
  });

  it("deletes nothing when no collection is open", async () => {
    const { result } = renderHook(() => useKBDetail(null), { wrapper });

    await act(async () => {
      await result.current.deleteDocument("d-1");
    });

    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("deletes the collection and stales the list the caller returns to", async () => {
    // The page navigates to `/kb` on success, and that list is a query this
    // hook does not own. Left cached, the collection that was just destroyed is
    // the first thing waiting there.
    client.setQueryData(qk.kb.list(), [{ id: "kb-1", name: "Handbook" }]);
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await act(async () => {
      await result.current.deleteCollection();
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/kb/kb-1");
    expect(client.getQueryState(qk.kb.list())?.isInvalidated).toBe(true);
    expect(toast.success).toHaveBeenCalledWith("Knowledge base deleted");
  });

  it("hands a refused collection deletion back rather than letting the page leave", async () => {
    // Swallowing this is how somebody lands on `/kb` with the collection still
    // in the list and a toast saying it could not be deleted.
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("Not yours to delete"));

    await expect(result.current.deleteCollection()).rejects.toThrow("Not yours to delete");
    expect(toast.error).toHaveBeenCalledWith("Not yours to delete");
  });

  it("names a collection deletion that failed without a sentence of its own", async () => {
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.delete).mockRejectedValue("boom");

    await expect(result.current.deleteCollection()).rejects.toBe("boom");
    expect(toast.error).toHaveBeenCalledWith("Failed to delete knowledge base");
  });

  it("deletes no collection when none is open", async () => {
    const { result } = renderHook(() => useKBDetail(null), { wrapper });

    await act(async () => {
      await result.current.deleteCollection();
    });

    expect(apiClient.delete).not.toHaveBeenCalled();
  });
});

describe("uploading a document", () => {
  it("posts the file to this app's own route, with credentials", async () => {
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await act(async () => {
      const upload = result.current.uploadDocument(new File(["x"], "a.pdf"));
      (await sent()).onload!();
      await upload;
    });

    expect(xhr().open).toHaveBeenCalledWith("POST", "/api/kb/kb-1/documents");
    expect(xhr().withCredentials).toBe(true);
    expect(toast.success).toHaveBeenCalledWith("Uploaded a.pdf");
  });

  it("uploads into the organization on screen, which XHR does not do for free", async () => {
    // The reason this is XHR at all is byte-level progress, which `fetch`
    // cannot report - but going around `apiClient` goes around the header it
    // attaches, and `/kb` is org-scoped. Without it the backend answers from
    // the personal organization, where this knowledge base does not exist, and
    // the upload fails for a reason nothing on screen explains.
    useOrgStore.setState({ activeOrgId: "org-b" });
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await act(async () => {
      const upload = result.current.uploadDocument(new File(["x"], "a.pdf"));
      (await sent()).onload!();
      await upload;
    });

    expect(xhr().setRequestHeader).toHaveBeenCalledWith("X-Organization-Id", "org-b");
  });

  it("reports progress as bytes go out, and clears it when the upload settles", async () => {
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    let upload: Promise<void>;
    await act(async () => {
      upload = result.current.uploadDocument(new File(["x"], "a.pdf"));
      await sent();
    });
    expect(result.current.isUploading).toBe(true);
    expect(result.current.uploadProgress[0]).toMatchObject({ filename: "a.pdf", percent: 0 });

    await act(async () => {
      xhr().upload.onprogress!({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
    });
    expect(result.current.uploadProgress[0]?.percent).toBe(50);

    await act(async () => {
      xhr().upload.onload!();
      xhr().onload!();
      await upload!;
    });
    expect(result.current.isUploading).toBe(false);
    expect(result.current.uploadProgress).toEqual([]);
  });

  it("says nothing about a percentage the browser cannot compute", async () => {
    // Which is what a chunked body reports; `0%` frozen on screen is worse than
    // an indeterminate bar.
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    let upload: Promise<void>;
    await act(async () => {
      upload = result.current.uploadDocument(new File(["x"], "a.pdf"));
      await sent();
    });

    await act(async () => {
      xhr().upload.onprogress!({ lengthComputable: false } as ProgressEvent);
    });
    expect(result.current.uploadProgress[0]?.percent).toBeNull();

    await act(async () => {
      xhr().onload!();
      await upload!;
    });
  });

  it("sends a per-upload parsing override only when it says something", async () => {
    // An empty object would mark the document as overridden for no reason.
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await act(async () => {
      const upload = result.current.uploadDocument(new File(["x"], "a.pdf"), {});
      (await sent(0)).onload!();
      await upload;
    });
    expect((xhr(0).send.mock.calls[0]![0] as FormData).get("ingestion")).toBeNull();

    await act(async () => {
      const upload = result.current.uploadDocument(new File(["x"], "b.pdf"), { ocr: true });
      (await sent(1)).onload!();
      await upload;
    });
    expect((xhr(1).send.mock.calls[0]![0] as FormData).get("ingestion")).toBe('{"ocr":true}');
  });

  it("reads the refusal out of the envelope the backend actually sends", async () => {
    // This looked for `detail`, so an unsupported extension, an oversized file and
    // a malformed override all arrived as "Upload failed".
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await act(async () => {
      const upload = result.current.uploadDocument(new File(["x"], "a.heic"));
      const request = await sent();
      request.status = 415;
      request.responseText = JSON.stringify({
        error: { code: "BAD_REQUEST", message: "PyMuPDF cannot read .heic", details: null },
      });
      request.onload!();
      await expect(upload).rejects.toThrow("PyMuPDF cannot read .heic");
    });

    expect(toast.error).toHaveBeenCalledWith("PyMuPDF cannot read .heic");
    expect(result.current.uploadProgress).toEqual([]);
  });

  it("still fails loudly when the refusal is not JSON at all", async () => {
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await act(async () => {
      const upload = result.current.uploadDocument(new File(["x"], "a.pdf"));
      const request = await sent();
      request.status = 502;
      request.responseText = "<html>Bad Gateway</html>";
      request.onload!();
      await expect(upload).rejects.toThrow("Upload failed");
    });
  });

  it("fails loudly when the upload never reached the server", async () => {
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    await act(async () => {
      const upload = result.current.uploadDocument(new File(["x"], "a.pdf"));
      (await sent()).onerror!();
      await expect(upload).rejects.toThrow("Upload failed");
    });

    expect(result.current.uploadProgress).toEqual([]);
  });

  it("tells two uploads of the same file apart", async () => {
    // A file can be uploaded twice; one progress entry for both would make the
    // second one's percentage overwrite the first's.
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });

    const one = result.current.uploadDocument(new File(["x"], "a.pdf"));
    const two = result.current.uploadDocument(new File(["x"], "a.pdf"));
    await waitFor(() => expect(result.current.uploadProgress).toHaveLength(2));

    const ids = result.current.uploadProgress.map((entry) => entry.uploadId);
    expect(new Set(ids).size).toBe(2);

    await act(async () => {
      (await sent(0)).onload!();
      (await sent(1)).onload!();
      await Promise.all([one, two]);
    });
    expect(result.current.uploadProgress).toEqual([]);
  });

  it("uploads nothing when no collection is open", async () => {
    const { result } = renderHook(() => useKBDetail(null), { wrapper });

    await act(async () => {
      await result.current.uploadDocument(new File(["x"], "a.pdf"));
    });

    expect(xhrs).toEqual([]);
  });
});

describe("the sync sources feeding a collection", () => {
  it("connects a source and shows it at the top", async () => {
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.syncSources).toHaveLength(1));
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s-new", name: "Dropbox" });

    await act(async () => {
      await result.current.createSyncSource({
        name: "Dropbox",
        connector_type: "dropbox",
        config: {},
      });
    });

    expect(apiClient.post).toHaveBeenCalledWith("/kb/kb-1/sync-sources", expect.any(Object));
    await waitFor(() => expect(result.current.syncSources[0]).toMatchObject({ id: "s-new" }));
  });

  it("reports a refused connection and raises it", async () => {
    // The wizard keeps its fields open on a refusal, so it needs the throw.
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Those credentials were refused"));

    await expect(
      result.current.createSyncSource({ name: "x", connector_type: "gdrive", config: {} }),
    ).rejects.toThrow();
    expect(toast.error).toHaveBeenCalledWith("Those credentials were refused");
  });

  it("falls back to its own sentence when a connection fails without one", async () => {
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.post).mockRejectedValue("boom");

    await expect(
      result.current.createSyncSource({ name: "x", connector_type: "gdrive", config: {} }),
    ).rejects.toBeTruthy();
    expect(toast.error).toHaveBeenCalledWith("Failed to create sync source");
  });

  it("moves a cloned org integration out of the offer list and into the collection's", async () => {
    // Otherwise it is offered again and cloning it twice produces two sources
    // pulling the same folder.
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.orgIntegrations).toHaveLength(1));
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s-clone", name: "Shared Drive" });

    await act(async () => {
      await result.current.cloneSyncSource("s-org", "handbook", "Shared Drive");
    });

    expect(apiClient.post).toHaveBeenCalledWith("/kb/kb-1/sync-sources/s-org/clone", {
      collection_name: "handbook",
      name: "Shared Drive",
    });
    await waitFor(() => expect(result.current.syncSources[0]).toMatchObject({ id: "s-clone" }));
    expect(result.current.orgIntegrations).toEqual([]);
  });

  it("reports a refused clone and raises it", async () => {
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.post).mockRejectedValue("boom");

    await expect(result.current.cloneSyncSource("s-org", "handbook", "x")).rejects.toBeTruthy();
    expect(toast.error).toHaveBeenCalledWith("Failed to clone integration");
  });

  it("triggers a sync and comes back for what it pulled in", async () => {
    // The worker ingests asynchronously, so the page re-reads shortly after
    // rather than showing an unchanged list.
    vi.useFakeTimers();
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await act(async () => {
      await result.current.triggerSyncSource("s-1");
    });
    expect(apiClient.post).toHaveBeenCalledWith("/kb/kb-1/sync-sources/s-1/trigger");
    const before = vi.mocked(apiClient.get).mock.calls.length;

    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });

    expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(before);
  });

  it("reports a refused trigger", async () => {
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Already running"));

    await act(async () => {
      await result.current.triggerSyncSource("s-1");
    });

    expect(toast.error).toHaveBeenCalledWith("Already running");
  });

  it("falls back to its own sentence for a trigger that failed without one", async () => {
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.post).mockRejectedValue("boom");

    await act(async () => {
      await result.current.triggerSyncSource("s-1");
    });

    expect(toast.error).toHaveBeenCalledWith("Failed to trigger sync");
  });

  it("removes a source from the list", async () => {
    serveDetail();
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    await waitFor(() => expect(result.current.syncSources).toHaveLength(1));

    await act(async () => {
      await result.current.deleteSyncSource("s-1");
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/kb/kb-1/sync-sources/s-1");
    await waitFor(() => expect(result.current.syncSources).toEqual([]));
  });

  it("reports a refused removal", async () => {
    const { result } = renderHook(() => useKBDetail("kb-1"), { wrapper });
    vi.mocked(apiClient.delete).mockRejectedValue("boom");

    await act(async () => {
      await result.current.deleteSyncSource("s-1");
    });

    expect(toast.error).toHaveBeenCalledWith("Failed to remove sync source");
  });

  it("does nothing to sources when no collection is open", async () => {
    const { result } = renderHook(() => useKBDetail(null), { wrapper });

    await act(async () => {
      await result.current.createSyncSource({ name: "x", connector_type: "g", config: {} });
      await result.current.cloneSyncSource("s", "c", "n");
      await result.current.triggerSyncSource("s");
      await result.current.deleteSyncSource("s");
    });

    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.delete).not.toHaveBeenCalled();
  });
});
