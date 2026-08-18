import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KBDetailPage from "./page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { KBDocument, KnowledgeBase } from "@/types";
import { Perm } from "@/types/permissions";

/**
 * What the strip under the title claims the collection holds.
 *
 * Documents page in twenty at a time, and this used to count the page: a
 * collection of fifty-seven said "20 documents", and pressing Load more made
 * the number climb - which reads as ingestion happening rather than as the page
 * correcting itself. So the document count is pinned to the query's own total,
 * and pinned to not moving when a second page arrives.
 *
 * The vector count has no such total anywhere the page reads, so what is pinned
 * there is that it says so: a partial sum names its scope, and only the sum
 * that really is the collection's is stated as one.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// `next/navigation` is mocked in `vitest.setup.ts`; nothing here asserts on a
// navigation, so there is no reason to shadow it.
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: string) => permission === Perm.collectionsView }),
}));

const COLLECTION: KnowledgeBase = {
  id: "kb-1",
  organization_id: "org-1",
  owner_user_id: null,
  name: "Handbook",
  description: "Everything HR keeps",
  collection_name: "org_handbook",
  scope: "org",
  is_default: false,
  ingestion_config: DEFAULT_INGESTION_CONFIG,
  embedding_model: "text-embedding-3-small",
  embedding_dim: 1536,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  // Zero, as the single-row read really answers - the three counts are derived
  // for the listing only. It is why the strip cannot read them off the base.
  document_count: 0,
  indexed_count: 0,
  chunk_count: 0,
};

function document_(index: number, chunks: number): KBDocument {
  return {
    id: `doc-${index}`,
    collection_name: "org_handbook",
    filename: `handbook-${index}.pdf`,
    filetype: "pdf",
    filesize: 1024,
    status: "completed",
    error_message: null,
    vector_document_id: `vec-${index}`,
    chunk_count: chunks,
    has_file: true,
    created_at: "2026-01-02T00:00:00Z",
    completed_at: "2026-01-02T00:01:00Z",
    parser: "pymupdf",
    image_description_model: null,
    embedding_model: "text-embedding-3-small",
    was_overridden: false,
  };
}

/**
 * Three documents to a page, four chunks each.
 *
 * Deliberately not the twenty `DOCS_PAGE_SIZE` really asks for
 * (`src/hooks/use-knowledge-bases.ts` - it is the frontend's constant, and the
 * route itself caps `limit` at 100). What the assertions need is a page
 * *shorter than the total*, and forty table rows to mount twice cost about two
 * seconds for one test - a spec that does more work than its assertions need is
 * the first to flake under coverage instrumentation, whatever `testTimeout` is
 * (#862).
 */
const FIRST_PAGE = Array.from({ length: 3 }, (_, i) => document_(i, 4));
const SECOND_PAGE = Array.from({ length: 3 }, (_, i) => document_(3 + i, 4));

/**
 * The page's five parallel reads, with the documents endpoint paging for real.
 *
 * `total` is the collection's; `items` is the slice `skip`/`limit` asked for.
 * Serving the total with a short page is the whole point - a mock that answers
 * every document at once cannot tell the two numbers apart.
 */
function serve({ total = 57 } = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/documents")) {
      const skip = Number(new URL(path, "http://x").searchParams.get("skip"));
      return { items: skip === 0 ? FIRST_PAGE : SECOND_PAGE, total };
    }
    if (path.endsWith("/connectors")) return { items: [] };
    if (path.includes("/sync-sources")) return { items: [], total: 0 };
    if (!path.startsWith("/kb/kb-1")) return { items: [], total: 0 };
    return COLLECTION;
  });
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

describe("the counts under a collection's title", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    serve();
  });

  it("states what the collection holds, not what the table fetched", async () => {
    await mount();

    expect(screen.getByText("57 documents")).toBeVisible();
    expect(screen.queryByText("3 documents")).toBeNull();
  });

  it("does not climb when a second page is loaded", async () => {
    await mount();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    // The second page really arrived - without this the assertion below would
    // pass against a button that did nothing.
    expect(await screen.findByText("handbook-5.pdf")).toBeVisible();
    expect(screen.getByText("57 documents")).toBeVisible();
    expect(screen.queryByText("6 documents")).toBeNull();
  });

  it("says a partial vector sum is only of what is loaded", async () => {
    // Three documents of four chunks, out of fifty-seven documents. Twelve is
    // the honest number for the three; it is not the collection's, and the page
    // has nothing that would let it claim otherwise.
    await mount();

    expect(screen.getByText("12 vectors in the documents loaded")).toBeVisible();
  });

  it("states the vector sum plainly once every document is loaded", async () => {
    // Nothing left to page in, so the sum over the table *is* the collection's.
    serve({ total: 3 });
    await mount();

    expect(screen.getByText("12 vectors")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });
});
