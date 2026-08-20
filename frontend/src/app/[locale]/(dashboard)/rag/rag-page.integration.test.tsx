import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RAGPage from "./page";
import { apiClient } from "@/lib/api-client";
import { searchDocuments } from "@/lib/rag-api";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import { useOrgStore } from "@/stores";
import type { KnowledgeBase } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("@/lib/rag-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/rag-api")>()),
  searchDocuments: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// Key-returning translator, the same convention as the sidebar tests: the
// assertions below name message keys, not English copy.
vi.mock("next-intl", () => ({
  useTranslations:
    (ns: string) =>
    (key: string): string =>
      `${ns}.${key}`,
}));

const perms = new Set<string>();
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (p: string) => perms.has(p) }),
}));

const ORG_ID = "org-1";

function kb(id: string, name: string, collection: string, isDefault = false): KnowledgeBase {
  return {
    id,
    name,
    description: null,
    collection_name: collection,
    scope: "org",
    organization_id: ORG_ID,
    owner_user_id: null,
    is_default: isDefault,
    ingestion_config: DEFAULT_INGESTION_CONFIG,
    embedding_model: "text-embedding-3-large",
    embedding_dim: 3072,
    rerank_model: null,
    rerank_secret_id: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    document_count: 0,
    indexed_count: 0,
    chunk_count: 0,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Routes the barrel of queries the page fans out to; `/kb` is the one under test. */
function mockApi(kbList: KnowledgeBase[] | Error) {
  vi.mocked(apiClient.get).mockImplementation((endpoint: string) => {
    if (endpoint === "/kb") {
      return kbList instanceof Error
        ? Promise.reject(kbList)
        : Promise.resolve({ items: kbList, total: kbList.length });
    }
    // The create dialog picks an embedding model, and renders straight from the
    // answer - an `{ items: [] }` shaped reply has no `models` to map over.
    if (endpoint === "/rag/embedding-models") {
      return Promise.resolve({
        default: "text-embedding-3-large",
        models: [{ model: "text-embedding-3-large", dimensions: 3072 }],
      });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
}

async function openSearchTab() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("tab", { name: "pages.kb.search" }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  perms.clear();
  perms.add("collections:view");
  useOrgStore.setState({ activeOrgId: ORG_ID });
  window.history.replaceState({}, "", "/rag");
});

// Deleting a collection is not on this page: it lives on the collection's own
// page, where the document count is on screen, and `delete-collection.integration
// .test.tsx` covers who is offered it there.
describe("write controls are gated on collections:edit (#31)", () => {
  it("a viewer sees no create button", async () => {
    mockApi([kb("kb-1", "Handbook", "handbook")]);

    render(<RAGPage />, { wrapper });

    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    expect(
      screen.queryByRole("button", { name: "pages.kb.newKnowledgeBase" }),
    ).not.toBeInTheDocument();
  });

  it("an editor sees it, so the viewer assertion is not passing vacuously", async () => {
    perms.add("collections:edit");
    mockApi([kb("kb-1", "Handbook", "handbook")]);

    render(<RAGPage />, { wrapper });

    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "pages.kb.newKnowledgeBase" })).toBeInTheDocument();
  });

  it("a viewer's empty state offers no create call-to-action", async () => {
    mockApi([]);

    render(<RAGPage />, { wrapper });

    await waitFor(() =>
      expect(screen.getByText("pages.kb.noKnowledgeBasesYet")).toBeInTheDocument(),
    );
    expect(screen.getByText("pages.kb.nothingHasBeenShared")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "pages.kb.createKnowledgeBase" }),
    ).not.toBeInTheDocument();
  });
});

describe("a failed list renders an error, not an empty state (#32)", () => {
  it("a 502 on /kb shows the error state instead of 'no knowledge bases yet'", async () => {
    mockApi(new Error("Bad gateway"));

    render(<RAGPage />, { wrapper });

    await waitFor(() => expect(screen.getByText("pages.kb.listFailedTitle")).toBeInTheDocument());
    expect(screen.queryByText("pages.kb.noKnowledgeBasesYet")).not.toBeInTheDocument();
  });

  it("the search tab says the list failed rather than that there is nothing to search", async () => {
    mockApi(new Error("Bad gateway"));
    window.history.replaceState({}, "", "/rag?tab=search");

    render(<RAGPage />, { wrapper });

    // The scope selector is built from the bases, so an empty array reads as
    // "you have none" - a claim the failed request never made.
    await waitFor(() => expect(screen.getByText("pages.kb.listFailedTitle")).toBeInTheDocument());
    expect(screen.queryByText("rag.search.noBases")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "pages.kb.retry" })).toBeInTheDocument();
  });
});

describe("search", () => {
  it("searches every readable base by default, deduplicating shared collections", async () => {
    mockApi([
      kb("kb-1", "Handbook", "handbook", true),
      kb("kb-2", "Contracts", "contracts"),
      kb("kb-3", "Handbook mirror", "handbook"),
    ]);
    vi.mocked(searchDocuments).mockResolvedValue({ results: [] });

    render(<RAGPage />, { wrapper });
    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    const user = await openSearchTab();

    await user.type(screen.getByPlaceholderText("rag.search.placeholder"), "onboarding");
    await user.click(screen.getByRole("button", { name: "rag.search.button" }));

    await waitFor(() =>
      expect(searchDocuments).toHaveBeenCalledWith({
        query: "onboarding",
        collection_names: ["handbook", "contracts"],
        limit: 10,
      }),
    );
  });

  it("holding Enter does not fire a second search over the first", async () => {
    mockApi([kb("kb-1", "Handbook", "handbook")]);
    let release: (v: { results: [] }) => void = () => {};
    vi.mocked(searchDocuments).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );

    render(<RAGPage />, { wrapper });
    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    const user = await openSearchTab();

    const input = screen.getByPlaceholderText("rag.search.placeholder");
    await user.type(input, "onboarding");
    // The button disables itself while a search is in flight; Enter did not, so
    // a second press raced the first and the slower answer painted last.
    await user.type(input, "{Enter}{Enter}");

    expect(searchDocuments).toHaveBeenCalledTimes(1);
    release({ results: [] });
  });

  it("a failed search renders the error state, not the no-results state", async () => {
    mockApi([kb("kb-1", "Handbook", "handbook")]);
    vi.mocked(searchDocuments).mockRejectedValue(new Error("Bad gateway"));

    render(<RAGPage />, { wrapper });
    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    const user = await openSearchTab();

    await user.type(screen.getByPlaceholderText("rag.search.placeholder"), "onboarding");
    await user.click(screen.getByRole("button", { name: "rag.search.button" }));

    await waitFor(() => expect(screen.getByText("rag.search.failedTitle")).toBeInTheDocument());
    expect(screen.queryByText("rag.search.noResults")).not.toBeInTheDocument();
    expect(screen.queryByText("rag.search.resultCount")).not.toBeInTheDocument();
  });

  it("an empty answer renders the no-results state with the result count", async () => {
    mockApi([kb("kb-1", "Handbook", "handbook")]);
    vi.mocked(searchDocuments).mockResolvedValue({ results: [] });

    render(<RAGPage />, { wrapper });
    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    const user = await openSearchTab();

    await user.type(screen.getByPlaceholderText("rag.search.placeholder"), "onboarding");
    await user.click(screen.getByRole("button", { name: "rag.search.button" }));

    await waitFor(() => expect(screen.getByText("rag.search.noResults")).toBeInTheDocument());
    expect(screen.getByText("rag.search.resultCount")).toBeInTheDocument();
    expect(screen.queryByText("rag.search.failedTitle")).not.toBeInTheDocument();
  });

  it("a result shows its source document, score and the base it came from", async () => {
    mockApi([kb("kb-1", "Handbook", "handbook")]);
    vi.mocked(searchDocuments).mockResolvedValue({
      results: [
        {
          content: "Vacations are requested through the portal.",
          score: 0.874,
          metadata: { filename: "handbook.pdf", page_num: 12, collection: "handbook" },
          parent_doc_id: "vec-1",
        },
      ],
    });

    render(<RAGPage />, { wrapper });
    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    const user = await openSearchTab();

    await user.type(screen.getByPlaceholderText("rag.search.placeholder"), "vacation");
    await user.click(screen.getByRole("button", { name: "rag.search.button" }));

    await waitFor(() => expect(screen.getByText("handbook.pdf")).toBeInTheDocument());
    expect(screen.getByText("0.874")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Handbook/ })).toHaveAttribute("href", "/rag/kb-1");
    expect(screen.getByText("Vacations are requested through the portal.")).toBeInTheDocument();
  });
});

describe("the three tabs each show only their own section (#939)", () => {
  it("shows the integrations panel instead of the base grid, not below it", async () => {
    // The defect this covers: the base list used to render for *every* value
    // that was not `search`, so choosing Integrations appended the panel under a
    // grid three rows deep - which is the placement the tab exists to fix.
    // The panel is gated on `connections:manage` - without it the section
    // returns null and there would be nothing to tell apart from the grid.
    perms.add("connections:manage");
    mockApi([kb("kb-1", "Handbook", "handbook")]);
    render(<RAGPage />, { wrapper });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "pages.kb.integrations" }));

    expect(await screen.findByText("kb.reusableIntegrations")).toBeInTheDocument();
    expect(screen.queryByText("pages.kb.bases")).not.toBeInTheDocument();
  });

  it("names the chosen tab in the URL, and leaves the default unnamed", async () => {
    // The write half. `useUrlState` rewrites the query string through
    // `setUrlParam`, so this reads the URL the page actually left behind.
    mockApi([kb("kb-1", "Handbook", "handbook")]);
    render(<RAGPage />, { wrapper });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "pages.kb.search" }));
    expect(new URLSearchParams(window.location.search).get("tab")).toBe("search");

    await user.click(screen.getByRole("tab", { name: "pages.kb.knowledgeBases" }));
    expect(new URLSearchParams(window.location.search).get("tab")).toBeNull();
  });

  // The read half - a pasted `?tab=` opening that section - belongs to
  // `useUrlState`, and `src/hooks/use-url-state.test.tsx` covers it. Asserting it
  // here would mean substituting `useSearchParams`, which the global mock in
  // `vitest.setup.ts` answers empty and wins: a test written that way passed
  // while the page rendered its default, which is worse than not having it.
});
