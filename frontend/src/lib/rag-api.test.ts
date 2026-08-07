import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as rag from "./rag-api";
import { ApiError, apiClient } from "./api-client";
import { useOrgStore } from "@/stores";

vi.mock("./api-client", async () => {
  const actual = await vi.importActual<typeof import("./api-client")>("./api-client");
  return {
    ...actual,
    // `raw` is the real one, over a stubbed `fetch`: what is under test is the
    // request it builds - the organization header above all - not that it ran.
    apiClient: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
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
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("search and parsed documents", () => {
  it("sends a search as a body, because a query is not a path", async () => {
    await rag.searchDocuments({ query: "refunds", limit: 5 });

    expect(apiClient.post).toHaveBeenCalledWith("/rag/search", { query: "refunds", limit: 5 });
  });

  it("reads what a parser made of one document", async () => {
    await rag.getParsedKBDocument("kb-1", "doc-1");

    expect(apiClient.get).toHaveBeenCalledWith("/kb/kb-1/documents/doc-1/parsed");
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

  it("saves the original bytes under the document's own filename", async () => {
    // Not the id: a file called `9f3c…pdf` in somebody's downloads folder is a
    // file they cannot find again.
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await rag.kbDocumentAccess("kb-1", { id: "d-1", filename: "handbook.pdf" }).download();

    const anchor = click.mock.instances[0] as HTMLAnchorElement;
    expect(anchor.download).toBe("handbook.pdf");
    click.mockRestore();
  });

  it("reads the document as bytes for what is rendered from them", async () => {
    const blob = new Blob(["%PDF-"], { type: "application/pdf" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, blob: () => Promise.resolve(blob) }),
    );

    const bytes = await rag
      .kbDocumentAccess("kb-1", { id: "d-1", filename: "handbook.pdf" })
      .readBytes();

    expect(bytes).toBe(blob);
  });

  it("keys its two bodies apart, because one route answers both", async () => {
    // Text and bytes come back from the same `/download`, so nothing but the key
    // stops a cached string being handed to a viewer showing a PDF.
    const access = rag.kbDocumentAccess("kb-1", { id: "d-1", filename: "handbook.pdf" });

    expect(access.textKey).not.toEqual(access.bytesKey);
  });

  it("reads the document as characters when that is what the viewer asked for", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: () => Promise.resolve("# Handbook"),
      }),
    );

    const text = await rag.kbDocumentAccess("kb-1", { id: "d-1", filename: "h.md" }).readText();

    expect(text).toEqual({ content: "# Handbook", truncated: false });
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
      .kbDocumentAccess("kb-1", { id: "d-1", filename: "handbook.pdf" })
      .download()
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(403);
  });

  it("reads the document from the organization on screen", async () => {
    // No header is not no tenant, it is the personal one.
    useOrgStore.getState().setActiveOrgId("org-b");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await rag.kbDocumentAccess("kb-1", { id: "d-1", filename: "handbook.pdf" }).download();

    const init = vi.mocked(fetch).mock.calls[0]![1] as { headers: Record<string, string> };
    expect(init.headers["X-Organization-Id"]).toBe("org-b");
    click.mockRestore();
  });
});
