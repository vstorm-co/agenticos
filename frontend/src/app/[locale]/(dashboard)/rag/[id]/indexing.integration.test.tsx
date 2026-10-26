import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KBDetailPage from "./page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { RAGCollectionInfo } from "@/lib/rag-api";
import type { KBDocument, KnowledgeBase } from "@/types";
import { Perm } from "@/types/permissions";

/**
 * Whether the collection is still indexing, as the strip under its title says.
 *
 * The collection-info endpoint said `complete` while 231 uploads were still
 * being ingested (#2486), and this page had no collection-level state at all -
 * only the badges of the twenty documents it had loaded, which settle long
 * before the rest of a large batch does. So the strip reads the collection's
 * own counts, and the poll keeps going while they say indexing even when every
 * loaded document has finished.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: string) => permission === Perm.collectionsView }),
}));

const COLLECTION: KnowledgeBase = {
  id: "kb-1",
  organization_id: "org-1",
  owner_user_id: null,
  name: "Handbook",
  description: "Everything HR keeps",
  collection_name: "org handbook",
  scope: "org",
  is_default: false,
  ingestion_config: DEFAULT_INGESTION_CONFIG,
  embedding_model: "text-embedding-3-small",
  embedding_provider: "openrouter",
  embedding_secret_id: null,
  embedding_endpoint_id: null,
  embedding_dim: 1536,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  document_count: 0,
  indexed_count: 0,
  chunk_count: 0,
};

/** One loaded document, already finished - the page of a batch that settled first. */
const SETTLED: KBDocument = {
  id: "doc-1",
  collection_name: "org handbook",
  filename: "handbook.pdf",
  filetype: "pdf",
  filesize: 1024,
  status: "done",
  error_message: null,
  vector_document_id: "vec-1",
  chunk_count: 4,
  has_file: true,
  created_at: "2026-01-02T00:00:00Z",
  completed_at: "2026-01-02T00:01:00Z",
  parser: "pymupdf",
  image_description_model: null,
  embedding_model: "text-embedding-3-small",
  was_overridden: false,
  organizational_unit: null,
};

const INFO_PATH = "/rag/collections/org%20handbook/info";

function info(overrides: Partial<RAGCollectionInfo>): RAGCollectionInfo {
  return {
    name: "org handbook",
    total_vectors: 111,
    dim: 1536,
    indexing_status: "complete",
    processing_count: 0,
    indexed_count: 0,
    failed_count: 0,
    ...overrides,
  };
}

/** The page's reads, with the collection info as given - or refused, for `null`. */
function serve(collectionInfo: RAGCollectionInfo | null) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === INFO_PATH) {
      if (collectionInfo === null) throw new Error("unavailable");
      return collectionInfo;
    }
    if (path.includes("/documents")) return { items: [SETTLED], total: 1 };
    if (path.endsWith("/connectors")) return { items: [] };
    if (path.includes("/sync-sources")) return { items: [], total: 0 };
    return COLLECTION;
  });
}

function infoReads(): number {
  return vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === INFO_PATH).length;
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>{children}</Suspense>
    </QueryClientProvider>
  );
}

async function mount() {
  await act(async () => {
    render(<KBDetailPage params={Promise.resolve({ id: "kb-1" })} />, { wrapper });
  });
  await screen.findByRole("heading", { name: "Handbook", level: 1 });
}

describe("a collection's indexing state on its page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says it is indexing while documents are still in progress", async () => {
    serve(info({ indexing_status: "indexing", processing_count: 220, indexed_count: 11 }));
    await mount();

    expect(await screen.findByText("Indexing: 220 documents in progress")).toBeVisible();
    expect(screen.queryByText("Indexing complete")).toBeNull();
  });

  it("says indexing is complete once nothing is in progress", async () => {
    serve(info({ indexed_count: 231 }));
    await mount();

    expect(await screen.findByText("Indexing complete")).toBeVisible();
    expect(screen.queryByText(/in progress/)).toBeNull();
  });

  it("shows failed documents beside the state, which they do not hold open", async () => {
    serve(info({ indexed_count: 229, failed_count: 2 }));
    await mount();

    expect(await screen.findByText("2 documents failed")).toBeVisible();
    expect(screen.getByText("Indexing complete")).toBeVisible();
  });

  it("does not announce an empty collection as indexed", async () => {
    serve(info({}));
    await mount();
    await waitFor(() => expect(infoReads()).toBe(1));

    expect(screen.queryByText("Indexing complete")).toBeNull();
    expect(screen.queryByText(/in progress/)).toBeNull();
  });

  it("says nothing about indexing when the state could not be read", async () => {
    serve(null);
    await mount();
    await waitFor(() => expect(infoReads()).toBe(1));

    // The page is still the collection's - the state is not load-bearing.
    expect(screen.getByText("handbook.pdf")).toBeVisible();
    expect(screen.queryByText("Indexing complete")).toBeNull();
    expect(screen.queryByText(/in progress/)).toBeNull();
  });

  it("keeps polling while the collection indexes, though every loaded document is done", async () => {
    // The one loaded document is `done`, so the loaded page alone would stop
    // the poll; the collection's own state is what keeps it going.
    serve(info({ indexing_status: "indexing", processing_count: 5, indexed_count: 1 }));
    await mount();
    await waitFor(() => expect(infoReads()).toBe(1));

    await waitFor(() => expect(infoReads()).toBeGreaterThan(1), { timeout: 5000 });
  });
});
