import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import catalog from "../../../../../messages/en.json";
import KBPage from "./page";
import KBDetailPage from "./[id]/page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { KBDocument, KnowledgeBase } from "@/types";
import { Perm } from "@/types/permissions";

/**
 * That the KB pages say nothing they wrote themselves.
 *
 * `scripts/check_i18n.py` cannot see any of the strings pinned here - a
 * one-word label, a template literal, a text node alone on its line, copy
 * behind an `&&` - so `make lint` was clean while the scope labels, the status
 * badges, the drop overlay and the table footer all rendered in English under
 * every locale.
 *
 * Asserting the English words would prove nothing: a hardcoded "Personal"
 * renders "Personal" too. So this file replaces the global `next-intl` mock
 * with one whose `pages.kb` messages are all marked, exactly as a translated
 * locale would differ from the source. A string the component still owns comes
 * out unmarked and fails.
 */

/** The prefix a "translation" carries. Repeated inside the hoisted factory
 *  below, which cannot reach anything declared out here. */
const MARK = "PL·";

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const en = (await import("../../../../../messages/en.json")).default;
  const mark = (message: string) => `PL·${message}`;
  const messages = {
    ...en,
    pages: {
      ...en.pages,
      kb: Object.fromEntries(Object.entries(en.pages.kb).map(([key, m]) => [key, mark(m)])),
    },
  };
  return {
    ...actual,
    useLocale: () => "pl",
    useMessages: () => messages,
    useFormatter: () => actual.createFormatter({ locale: "pl" }),
    useTranslations: (namespace?: string) =>
      actual.createTranslator({
        locale: "pl",
        messages: messages as Parameters<typeof actual.createTranslator>[0]["messages"],
        namespace: namespace as never,
      }),
  };
});

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/kb",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: "kb-1" }),
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: string) => permission === Perm.collectionsEdit }),
}));

const COLLECTION: KnowledgeBase = {
  id: "kb-1",
  organization_id: "org-1",
  owner_user_id: null,
  name: "Handbook",
  description: "Everything HR keeps",
  collection_name: "org_handbook",
  scope: "org",
  is_default: true,
  ingestion_config: DEFAULT_INGESTION_CONFIG,
  embedding_model: "text-embedding-3-small",
  embedding_dim: 1536,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
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

const SOURCE = {
  id: "src-1",
  name: "Drive",
  connector_type: "gdrive",
  schedule_minutes: 30,
  last_sync_at: null,
  last_sync_status: null,
  last_error: null,
};

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    // Not a list, and the create dialog builds its model select straight off
    // `models` rather than tolerating whatever arrives - so the catch-all below
    // would hand it `{items, total}` and it would throw on mount.
    if (path === "/rag/embedding-models") {
      return {
        default: "text-embedding-3-large",
        models: [{ model: "text-embedding-3-large", dim: 3072 }],
      };
    }
    if (path.includes("/documents")) return { items: [DOCUMENT], total: 57 };
    if (path.endsWith("/connectors")) return { items: [] };
    if (path.endsWith("/sync-sources")) return { items: [SOURCE], total: 1 };
    if (path.includes("/sync-sources")) return { items: [], total: 0 };
    if (path === "/kb") return { items: [COLLECTION], total: 1 };
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

async function mountDetail() {
  await act(async () => {
    render(<KBDetailPage params={Promise.resolve({ id: "kb-1" })} />, { wrapper });
  });
  await screen.findByRole("heading", { name: "Handbook", level: 1 });
}

beforeEach(() => {
  vi.clearAllMocks();
  serve();
});

describe("what a collection's own page says", () => {
  it("takes its scope word and its default marker from the catalog", async () => {
    await mountDetail();

    expect(screen.getByText(`${MARK}Organization · ${MARK}Default`)).toBeVisible();
  });

  it("takes a document's status badge from the catalog", async () => {
    await mountDetail();

    expect(screen.getByText(`${MARK}Ready`)).toBeVisible();
  });

  it("counts a document's chunks through a plural message", async () => {
    // `· ${doc.chunk_count} chunks` was a template literal, which the guard's
    // two-word threshold reads past - and a trailing `s` is a plural only
    // English builds that way.
    await mountDetail();

    expect(screen.getByText(new RegExp(`${MARK}12 chunks`))).toBeVisible();
  });

  it("counts the table's own footer through a plural message", async () => {
    await mountDetail();

    expect(
      screen.getByText(`${MARK}Showing 1 of 57 documents · drag files anywhere to add`),
    ).toBeVisible();
  });

  it("takes a sync source's schedule from the catalog", async () => {
    await mountDetail();

    expect(screen.getByText(`${MARK}every 30m`)).toBeVisible();
  });

  it("names the collection in the drop overlay, in words a translator can reach", async () => {
    // Also what pins the drag detection itself: the `DataTransfer` type is the
    // literal "Files", which used to be read out of the catalog as `files2`.
    // Translated, it would never match and this overlay would never appear.
    await mountDetail();

    fireEvent.dragEnter(screen.getByRole("heading", { name: "Handbook", level: 1 }), {
      dataTransfer: { types: ["Files"] },
    });

    const overlay = await screen.findByText(`${MARK}Drop to upload`);
    expect(overlay.parentElement).toHaveTextContent(`${MARK}Files will be added to Handbook`);
  });
});

describe("what the list of collections says", () => {
  it("takes a card's scope word from the catalog", async () => {
    await act(async () => {
      render(<KBPage />, { wrapper });
    });

    expect(await screen.findByText(`${MARK}Organization`)).toBeVisible();
  });

  it("draws the card's own class list rather than reading one out of the catalog", async () => {
    await act(async () => {
      render(<KBPage />, { wrapper });
    });

    const card = (await screen.findByRole("link", { name: `${MARK}Open Handbook` })).parentElement;
    expect(card).toHaveClass("bg-card");
    // Marked, had it come through `t()` - `cn()` would have been handed
    // "PL·group border-border …" and the card would have lost every style.
    expect(card?.className).not.toContain(MARK);
    // The `group-hover` that needed it was on the delete button #303 removed.
    expect(card?.className.split(/\s+/)).not.toContain("group");
  });
});

describe("the catalog itself", () => {
  it("holds no Tailwind and no DataTransfer type under pages.kb", () => {
    // `groupBorderBorderBg2`, `files2` and `files3` were all in here: a class
    // list and, twice, the DOM's own name for a dragged file. Neither is
    // something a person reads, and both break when somebody translates them.
    const kb: Record<string, string> = catalog.pages.kb;

    expect(Object.keys(kb)).not.toContain("groupBorderBorderBg2");
    expect(Object.keys(kb)).not.toContain("files2");
    expect(Object.keys(kb)).not.toContain("files3");
    for (const [key, message] of Object.entries(kb)) {
      expect(message, key).not.toMatch(/(?:^|\s)(?:flex|rounded-xl|bg-card|border-border)(?:\s|$)/);
    }
  });
});
