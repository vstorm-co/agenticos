import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KBDetailPage from "./page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { KBDocument, KnowledgeBase } from "@/types";
import type { Permission } from "@/types/permissions";
import { Perm } from "@/types/permissions";

/**
 * Deleting a collection, from the one page that says what is in it.
 *
 * It used to be a hover-revealed trash icon on the card in the list, sitting on
 * top of a whole-card link - one mis-aimed click away from *opening* the
 * collection - and guarded by a `window.confirm` holding a hardcoded English
 * sentence. So what is pinned here is the shape that replaced it: the control
 * exists for somebody holding `collections:edit`, does not exist at all for a
 * Viewer, and reaches the server only through a confirmation that names the
 * collection and how much of it is about to go.
 *
 * The document count is the collection's, not the table's. Documents page in
 * twenty at a time, and a dialog that promises to destroy twenty of fifty-seven
 * is a dialog somebody would be right to believe.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/rag/kb-1",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: "kb-1" }),
}));

/** What the caller holds in the active organization, per test. */
let held: Permission[] = [];
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: Permission) => held.includes(permission) }),
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
  embedding_provider: "openrouter",
  embedding_secret_id: null,
  embedding_dim: 1536,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  // Zero, as the single-row read really answers: the three counts are derived
  // for the listing only. It is why the confirmation reads its number off the
  // document query's total instead.
  document_count: 0,
  indexed_count: 0,
  chunk_count: 0,
};

const DOCUMENT: KBDocument = {
  id: "doc-1",
  collection_name: "org_handbook",
  filename: "handbook.pdf",
  filetype: "pdf",
  filesize: 1024,
  status: "completed",
  error_message: null,
  vector_document_id: "vec-1",
  chunk_count: 12,
  has_file: true,
  created_at: "2026-01-02T00:00:00Z",
  completed_at: "2026-01-02T00:01:00Z",
  parser: "pymupdf",
  image_description_model: null,
  embedding_model: "text-embedding-3-small",
  was_overridden: false,
};

/**
 * The page's five parallel reads. Three of them sit behind their own permission
 * and are allowed to answer empty, which is what a Viewer actually gets.
 */
function serve({ documentsTotal = 57, sources = [] as unknown[], isDefault = false } = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/documents")) return { items: [DOCUMENT], total: documentsTotal };
    if (path.endsWith("/connectors")) return { items: [] };
    if (path.endsWith("/sync-sources")) return { items: sources, total: sources.length };
    if (path.includes("/sync-sources")) return { items: [], total: 0 };
    // Whatever the dashboard chrome asks for on the way past.
    if (!path.startsWith("/kb/kb-1")) return { items: [], total: 0 };
    return { ...COLLECTION, is_default: isDefault };
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      {/* The page reads its id with `use(params)`, which suspends once. */}
      <Suspense fallback={null}>{children}</Suspense>
    </QueryClientProvider>
  );
}

/**
 * Select a section's tab.
 *
 * The three sections are tabs since #939, so a test asserting on the sync
 * sources has to choose that tab first - previously they were all stacked and
 * everything was on screen at once.
 */
async function openTab(name: string) {
  // `find`, not `get`: the page draws a skeleton until its collection arrives, so
  // a `get` here races the first render rather than the tab being absent.
  await userEvent.click(await screen.findByRole("tab", { name }));
}

async function mount() {
  // Awaited, because `use(params)` suspends on the first render and React warns
  // - then leaves the fallback on screen - if that resolution lands outside an
  // `act` scope somebody waited for.
  await act(async () => {
    render(<KBDetailPage params={Promise.resolve({ id: "kb-1" })} />, { wrapper });
  });
  await screen.findByRole("heading", { name: "Handbook", level: 1 });
}

describe("deleting a collection from its own page", () => {
  beforeEach(() => {
    // The page writes its tab into the URL, and jsdom's location persists across
    // tests in a file - so without this a test that opened Sync sources leaves the
    // next one mounting on that tab. A browser gets a fresh URL per navigation.
    window.history.replaceState({}, "", "/");
    vi.clearAllMocks();
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    held = [Perm.collectionsView, Perm.collectionsEdit];
    serve();
  });

  it("offers Delete to a caller holding collections:edit", async () => {
    await mount();

    await userEvent.click(screen.getByRole("button", { name: "More actions" }));

    expect(screen.getByRole("menuitem", { name: "Delete knowledge base" })).toBeVisible();
  });

  it("offers a Viewer without a grant no way to delete it at all", async () => {
    // Not rendered, rather than rendered and then refused by the server. The
    // menu that holds it is the only route to the action, so its absence is the
    // whole assertion - querying for the item inside a menu nobody opened would
    // pass for a caller who does hold the permission too.
    held = [Perm.collectionsView];
    await mount();

    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
    // Upload goes with it, which is the difference between this and the
    // default-collection case below - there, only the menu is withheld.
    expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
  });

  it("offers no delete for the default collection, which the server refuses", async () => {
    // `KnowledgeBaseService.delete` answers 400 for it, so the menu holding the
    // only item would open onto an action that cannot work. Upload stays: the
    // caller may still write to it.
    serve({ isDefault: true });
    await mount();

    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
    expect(screen.getByRole("button", { name: "Upload" })).toBeVisible();
  });

  it("names the collection and everything in it before destroying either", async () => {
    await mount();
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete knowledge base" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Delete Handbook?");
    // 57, not the one document the first page of the table holds.
    expect(dialog).toHaveTextContent("all 57 documents in it");
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("deletes the collection on confirmation and returns to the list", async () => {
    await mount();
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete knowledge base" }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/kb/kb-1"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/rag"));
  });

  it("keeps the reader on a collection the server refused to delete", async () => {
    // The toast says why. Navigating anyway would land somebody on `/kb` with
    // the collection still in the list.
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("Not yours to delete"));
    await mount();
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete knowledge base" }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalled());
    expect(push).not.toHaveBeenCalled();
  });
});

describe("the other two confirmations on the page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    held = [Perm.collectionsView, Perm.collectionsEdit];
    serve();
  });

  it("asks before removing a document, in words a translator can reach", async () => {
    // This was `confirm("Remove \"…\" from this knowledge base?")` - copy no locale
    // could reach, and one no guard reported until #395 read a call's arguments.
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Remove document" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Remove handbook.pdf?");
    expect(apiClient.delete).not.toHaveBeenCalled();

    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/kb/kb-1/documents/doc-1"));
  });

  it("asks before disconnecting a sync source, and says what stays behind", async () => {
    serve({ sources: [{ id: "src-1", name: "Drive", connector_type: "gdrive" }] });
    await mount();
    await openTab("Sync sources");

    await userEvent.click(await screen.findByRole("button", { name: "Remove source" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Disconnect Drive?");
    expect(dialog).toHaveTextContent("Documents already ingested stay where they are.");
    expect(apiClient.delete).not.toHaveBeenCalled();

    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith("/kb/kb-1/sync-sources/src-1"),
    );
  });
});
