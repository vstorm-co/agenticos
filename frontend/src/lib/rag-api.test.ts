import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as rag from "./rag-api";
import { ApiError, apiClient } from "./api-client";
import { useOrgStore } from "@/stores";

vi.mock("./api-client", async () => {
  const actual = await vi.importActual<typeof import("./api-client")>("./api-client");
  return {
    ...actual,
    // `upload` and `raw` are the real ones, over a stubbed `fetch`. What they
    // are being tested for is the request they build - the organization header
    // above all - and a mock of them would assert only that they were called.
    apiClient: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
      upload: actual.apiClient.upload.bind(actual.apiClient),
      raw: actual.apiClient.raw.bind(actual.apiClient),
    },
  };
});

/**
 * The RAG endpoints, as paths and payloads.
 *
 * Thin by design - there is nothing to assert about a wrapper except the two
 * things a typo silently breaks: which URL it addresses, and what it sends. A
 * wrong path here answers 404 in a panel that renders its empty state, so the
 * failure looks like "no documents" rather than like a bug.
 */
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "x" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "x" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("collections and documents", () => {
  it("addresses each collection route by name", async () => {
    await rag.listCollections();
    expect(apiClient.get).toHaveBeenCalledWith("/rag/collections");

    await rag.getCollectionInfo("handbook");
    expect(apiClient.get).toHaveBeenCalledWith("/rag/collections/handbook/info");

    await rag.createCollection("handbook");
    expect(apiClient.post).toHaveBeenCalledWith("/rag/collections/handbook");

    await rag.deleteCollection("handbook");
    expect(apiClient.delete).toHaveBeenCalledWith("/rag/collections/handbook");

    await rag.deleteDocument("handbook", "d-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/rag/collections/handbook/documents/d-1");

    await rag.listDocuments("handbook");
    expect(apiClient.get).toHaveBeenCalledWith("/rag/collections/handbook/documents");
  });

  it("sends a search as a body, because a query is not a path", async () => {
    await rag.searchDocuments({ query: "refunds", limit: 5 });

    expect(apiClient.post).toHaveBeenCalledWith("/rag/search", { query: "refunds", limit: 5 });
  });

  it("narrows the tracked-document list to one collection, escaping the name", async () => {
    // Collection names are user-typed; an unescaped space produces a URL the
    // proxy rejects.
    await rag.listTrackedDocuments("HR handbook");

    expect(apiClient.get).toHaveBeenCalledWith("/rag/documents?collection_name=HR%20handbook");
  });

  it("lists every tracked document when no collection is named", async () => {
    await rag.listTrackedDocuments();

    expect(apiClient.get).toHaveBeenCalledWith("/rag/documents");
  });

  it("deletes a tracked document by its own id, not the vector's", async () => {
    await rag.deleteTrackedDocument("doc-1");

    expect(apiClient.delete).toHaveBeenCalledWith("/rag/documents/doc-1");
  });

  it("reads what a parser made of one document", async () => {
    await rag.getParsedKBDocument("kb-1", "doc-1");

    expect(apiClient.get).toHaveBeenCalledWith("/kb/kb-1/documents/doc-1/parsed");
  });

  it("addresses the original bytes through this app's own route", () => {
    expect(rag.getDocumentDownloadUrl("doc-1")).toBe("/api/rag/documents/doc-1/download");
  });
});

describe("sync sources", () => {
  it("addresses every source route", async () => {
    await rag.listSyncSources();
    expect(apiClient.get).toHaveBeenCalledWith("/rag/sync/sources");

    await rag.listSyncSources("HR handbook");
    expect(apiClient.get).toHaveBeenCalledWith("/rag/sync/sources?collection_name=HR%20handbook");

    await rag.createSyncSource({ name: "Drive", connector_type: "gdrive", config: {} });
    expect(apiClient.post).toHaveBeenCalledWith("/rag/sync/sources", {
      name: "Drive",
      connector_type: "gdrive",
      config: {},
    });

    await rag.cloneSyncSource("s-1", { collection_name: "handbook" });
    expect(apiClient.post).toHaveBeenCalledWith("/rag/sync/sources/s-1/clone", {
      collection_name: "handbook",
    });

    await rag.updateSyncSource("s-1", { schedule_minutes: 60 });
    expect(apiClient.patch).toHaveBeenCalledWith("/rag/sync/sources/s-1", {
      schedule_minutes: 60,
    });

    await rag.deleteSyncSource("s-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/rag/sync/sources/s-1");

    await rag.triggerSyncSource("s-1");
    expect(apiClient.post).toHaveBeenCalledWith("/rag/sync/sources/s-1/trigger");

    await rag.listConnectors();
    expect(apiClient.get).toHaveBeenCalledWith("/rag/sync/connectors");
  });

  it("reads sync logs, for everything or for one collection", async () => {
    await rag.listSyncLogs();
    expect(apiClient.get).toHaveBeenCalledWith("/rag/sync/logs?limit=20");

    await rag.listSyncLogs("handbook", 5);
    expect(apiClient.get).toHaveBeenCalledWith("/rag/sync/logs?collection_name=handbook&limit=5");
  });

  it("reads the logs of one source under a knowledge base", async () => {
    await rag.listKBSyncSourceLogs("kb-1", "s-1", 5);

    expect(apiClient.get).toHaveBeenCalledWith("/kb/kb-1/sync-sources/s-1/logs?limit=5");
  });

  it("starts and cancels a local sync", async () => {
    await rag.triggerSync("handbook", "full", "/srv/docs");
    expect(apiClient.post).toHaveBeenCalledWith("/rag/sync/local", {
      collection_name: "handbook",
      mode: "full",
      path: "/srv/docs",
    });

    await rag.cancelSync("sync-1");
    expect(apiClient.delete).toHaveBeenCalledWith("/rag/sync/sync-1");
  });
});

describe("isRagEnabled", () => {
  it("is on only when the deployment says so, in those exact words", async () => {
    vi.stubEnv("NEXT_PUBLIC_RAG_ENABLED", "true");
    expect(rag.isRagEnabled()).toBe(true);

    // Anything else is off - `"1"` and `"TRUE"` included, because the value is
    // compared rather than coerced.
    vi.stubEnv("NEXT_PUBLIC_RAG_ENABLED", "1");
    expect(rag.isRagEnabled()).toBe(false);

    vi.stubEnv("NEXT_PUBLIC_RAG_ENABLED", undefined);
    expect(rag.isRagEnabled()).toBe(false);
  });
});

describe("ingesting a file", () => {
  /**
   * A stubbed response, with `text` derived from `json`.
   *
   * The real client reads the body as text and parses it, which is how it
   * answers `null` to an empty 204 rather than throwing on `JSON.parse("")`.
   */
  function respond(response: Partial<Response> & { json: () => Promise<unknown> }) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => response.json().then((body) => JSON.stringify(body)),
      ...response,
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("posts the file as multipart, to the collection it belongs to", async () => {
    const fetchMock = respond({ json: () => Promise.resolve({ id: "i-1", status: "processing" }) });

    await rag.ingestFile("handbook", new File(["x"], "a.pdf"));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/rag/collections/handbook/ingest");
    expect(init.method).toBe("POST");
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
    // No `Content-Type`: only the browser knows the boundary it generated, and
    // naming the type by hand drops it.
    expect(init.headers).not.toHaveProperty("Content-Type");
  });

  it("ingests into the organization on screen, not the caller's personal one", async () => {
    // The whole reason this goes through `apiClient`. A request with no
    // `X-Organization-Id` is not tenant-less - the backend falls back to the
    // personal organization - so a bare `fetch` wrote the file to a different
    // tenant and reported success under this one.
    useOrgStore.getState().setActiveOrgId("org-b");
    const fetchMock = respond({ json: () => Promise.resolve({}) });

    await rag.ingestFile("handbook", new File(["x"], "a.pdf"));

    expect(fetchMock.mock.calls[0]![1].headers["X-Organization-Id"]).toBe("org-b");
  });

  it("asks for a replace explicitly, because the default must not overwrite", async () => {
    const fetchMock = respond({ json: () => Promise.resolve({}) });

    await rag.ingestFile("handbook", new File(["x"], "a.pdf"), true);

    expect(fetchMock.mock.calls[0]![0]).toBe("/api/rag/collections/handbook/ingest?replace=true");
  });

  it("raises the server's own refusal, with its status", async () => {
    // "This format is not supported" is the sentence the upload panel shows.
    respond({
      ok: false,
      status: 415,
      text: () => Promise.resolve(""),
      json: () => Promise.resolve({ detail: "Unsupported format: .heic" }),
    });

    const failure = await rag
      .ingestFile("handbook", new File(["x"], "a.heic"))
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(415);
    expect((failure as ApiError).message).toBe("Unsupported format: .heic");
  });

  it("still fails loudly when the refusal is not JSON, or names no reason", async () => {
    respond({ ok: false, status: 502, json: () => Promise.reject(new Error("not json")) });
    await expect(rag.ingestFile("handbook", new File(["x"], "a.pdf"))).rejects.toThrow(
      "Request failed",
    );

    respond({ ok: false, status: 500, json: () => Promise.resolve({}) });
    await expect(rag.ingestFile("handbook", new File(["x"], "a.pdf"))).rejects.toThrow(
      "Request failed",
    );
  });
});

describe("downloading a knowledge-base document", () => {
  const created: string[] = [];
  const revoked: string[] = [];

  beforeEach(() => {
    created.length = 0;
    revoked.length = 0;
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => {
        const url = `blob:${created.length}`;
        created.push(url);
        return url;
      }),
      revokeObjectURL: vi.fn((url: string) => revoked.push(url)),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, blob: () => Promise.resolve(new Blob()) }),
    );
    useOrgStore.getState().setActiveOrgId(null);
  });

  it("holds the viewing URL open for a minute, then releases it", async () => {
    // Revoking straight away would close the tab that was just opened; never
    // revoking leaks the blob for the life of the page. The delay is the whole
    // behaviour, so the timer has to be run to see it.
    vi.useFakeTimers();
    const open = vi.spyOn(window, "open").mockReturnValue(null);

    await rag.downloadKBDocument("kb-1", { id: "d-1", filename: "handbook.pdf" }, "view");

    expect(open).toHaveBeenCalled();
    expect(revoked).toEqual([]);
    vi.advanceTimersByTime(60_000);
    expect(revoked).toEqual(created);

    open.mockRestore();
    vi.useRealTimers();
  });

  it("saves the original bytes under the document's own filename", async () => {
    // Not the id: a file called `9f3c…pdf` in somebody's downloads folder is a
    // file they cannot find again.
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await rag.downloadKBDocument("kb-1", { id: "d-1", filename: "handbook.pdf" });

    expect(click).toHaveBeenCalled();
    expect(revoked).toEqual(created);
    click.mockRestore();
  });

  it("opens a document for reading in a tab that cannot reach back", async () => {
    // `noopener` because the blob is rendered by the browser and the opened
    // context has no business touching this one.
    const open = vi.fn();
    vi.stubGlobal("open", open);

    await rag.downloadKBDocument("kb-1", { id: "d-1", filename: "handbook.pdf" }, "view");

    expect(open).toHaveBeenCalledWith("blob:0", "_blank", "noopener,noreferrer");
    // Revoked on a timer rather than at once: revoking it immediately closes the
    // tab that was just opened.
    expect(revoked).toEqual([]);
  });

  it("says the download failed rather than saving an empty file", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        json: () => Promise.resolve({ detail: "Not your knowledge base" }),
      }),
    );

    const failure = await rag
      .downloadKBDocument("kb-1", { id: "d-1", filename: "handbook.pdf" })
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(403);
  });

  it("reads the document from the organization on screen", async () => {
    // Same reason as the ingest: no header is not no tenant, it is the personal
    // one, so this used to fetch a knowledge base the page was not showing.
    useOrgStore.getState().setActiveOrgId("org-b");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await rag.downloadKBDocument("kb-1", { id: "d-1", filename: "handbook.pdf" });

    const init = vi.mocked(fetch).mock.calls[0]![1] as { headers: Record<string, string> };
    expect(init.headers["X-Organization-Id"]).toBe("org-b");
    click.mockRestore();
  });
});
