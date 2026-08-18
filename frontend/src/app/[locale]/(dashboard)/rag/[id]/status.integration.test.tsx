import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KBDetailPage from "./page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { SyncSourceRead } from "@/lib/rag-api";
import type { KBDocument, KnowledgeBase } from "@/types";
import { Perm } from "@/types/permissions";

/**
 * That a failure is drawn as one.
 *
 * Both badges on this page compared against words nothing writes - the sync
 * badge tested `failed` and the document badge mapped
 * `completed`/`pending`/`failed`, while the worker writes `done` and `error`
 * (#356). So each assertion here is a *comparison* between the two rows rather
 * than a check that a label is on screen: a label being present passed against
 * the broken code, because the fall-through printed the raw token and the
 * colour branch was simply never taken. What could not pass was "these two look
 * different".
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
  collection_name: "org_handbook",
  scope: "org",
  is_default: false,
  ingestion_config: DEFAULT_INGESTION_CONFIG,
  embedding_model: "text-embedding-3-small",
  embedding_dim: 1536,
  rerank_model: null,
  rerank_secret_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  document_count: 2,
  indexed_count: 1,
  chunk_count: 4,
};

/** Statuses as `app/services/rag_document.py` writes them, not as the badge guessed. */
function document_(id: string, status: string, error: string | null): KBDocument {
  return {
    id,
    collection_name: "org_handbook",
    filename: `${id}.pdf`,
    filetype: "pdf",
    filesize: 1024,
    status,
    error_message: error,
    vector_document_id: error === null ? `vec-${id}` : null,
    chunk_count: error === null ? 4 : 0,
    has_file: true,
    created_at: "2026-01-02T00:00:00Z",
    completed_at: "2026-01-02T00:01:00Z",
    parser: "pymupdf",
    image_description_model: null,
    embedding_model: "text-embedding-3-small",
    was_overridden: false,
  };
}

/** As `app/worker/tasks/rag_tasks.py` writes it: `done` if nothing failed, else `error`. */
function source(id: string, status: string, error: string | null): SyncSourceRead {
  return {
    id,
    organization_id: "org-1",
    name: `${id} drive`,
    connector_type: "gdrive",
    collection_name: "org_handbook",
    config: {},
    sync_mode: "full",
    schedule_minutes: 60,
    is_active: true,
    last_sync_at: "2026-01-03T00:00:00Z",
    last_sync_status: status,
    last_error: error,
    created_at: "2026-01-01T00:00:00Z",
  };
}

const DOCUMENTS = [
  document_("finished", "done", null),
  document_("broken", "error", "The parser gave up on page 4"),
];

const SOURCES = [source("working", "done", null), source("broken", "error", "Token revoked")];

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/documents")) return { items: DOCUMENTS, total: DOCUMENTS.length };
    if (path.endsWith("/connectors")) return { items: [] };
    if (path.includes("/sync-sources")) return { items: SOURCES, total: SOURCES.length };
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

describe("a status badge on a knowledge base", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    serve();
  });

  it("colours a failed sync source unlike the one that worked", async () => {
    await mount();

    // The failure is found by the explanation hung off it, so this names the
    // sync source's badge and not the document's.
    const failed = screen.getByTitle("Token revoked");
    expect(failed).toHaveTextContent("Failed");
    expect(failed).toHaveClass("text-destructive");

    for (const succeeded of screen.getAllByText("Done")) {
      expect(succeeded).not.toHaveClass("text-destructive");
    }
  });

  it("colours a failed document unlike the one that was ingested", async () => {
    await mount();

    const failed = screen.getByTitle("The parser gave up on page 4");
    expect(failed).toHaveTextContent("Failed");
    expect(failed).toHaveClass("text-destructive");
  });

  it("says what happened in words rather than in the column's own token", async () => {
    await mount();

    // `error` and `done` are what the worker writes; neither belongs on screen.
    expect(screen.queryByText("error")).toBeNull();
    expect(screen.queryByText("done")).toBeNull();
    expect(screen.getAllByText("Failed").length).toBe(2); // one document, one source
    expect(screen.getAllByText("Done").length).toBe(2);
  });

  it("keeps the server's own token for a status this build does not know", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.includes("/documents")) {
        return { items: [document_("odd", "quarantined", null)], total: 1 };
      }
      if (path.endsWith("/connectors")) return { items: [] };
      if (path.includes("/sync-sources")) return { items: [], total: 0 };
      if (!path.startsWith("/kb/kb-1")) return { items: [], total: 0 };
      return COLLECTION;
    });
    await mount();

    // Not a word this build invented for it, and not blank.
    expect(screen.getByText("quarantined")).toBeVisible();
    expect(screen.getByText("quarantined")).not.toHaveClass("text-destructive");
  });

  it("leaves a badge that did not fail with nothing to explain", async () => {
    await mount();

    for (const succeeded of screen.getAllByText("Done")) {
      expect(succeeded).not.toHaveAttribute("title");
    }
  });
});
