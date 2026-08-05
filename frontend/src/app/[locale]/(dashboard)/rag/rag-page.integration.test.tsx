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
    return Promise.resolve({ items: [], total: 0 });
  });
}

async function openSearchTab() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "pages.kb.search" }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  perms.clear();
  perms.add("collections:view");
  useOrgStore.setState({ activeOrgId: ORG_ID });
  window.history.replaceState({}, "", "/rag");
});

describe("write controls are gated on collections:edit (#31)", () => {
  it("a viewer sees neither the create button nor a delete control", async () => {
    mockApi([kb("kb-1", "Handbook", "handbook")]);

    render(<RAGPage />, { wrapper });

    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    expect(
      screen.queryByRole("button", { name: "pages.kb.newKnowledgeBase" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "pages.kb.deleteKnowledgeBase" }),
    ).not.toBeInTheDocument();
  });

  it("an editor sees both, so the viewer assertion is not passing vacuously", async () => {
    perms.add("collections:edit");
    mockApi([kb("kb-1", "Handbook", "handbook")]);

    render(<RAGPage />, { wrapper });

    await waitFor(() => expect(screen.getByText("Handbook")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "pages.kb.newKnowledgeBase" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "pages.kb.deleteKnowledgeBase" }),
    ).toBeInTheDocument();
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
