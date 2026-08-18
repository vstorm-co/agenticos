import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RerankPanel } from "./rerank-panel";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { KnowledgeBase } from "@/types/knowledge-base";

/**
 * The panel is what tells someone reading a collection whether its searches are
 * reranked, and with which key - a retrieval-time fact that changes on a
 * different day than how the documents were read, which is why it is its own
 * section rather than a line in the ingestion panel.
 */

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const SECRETS = {
  items: [{ id: "co-1", name: "Cohere prod", hint: "4242", purpose: "cohere", kind: "api_key" }],
  total: 1,
};

function kb(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
  return {
    id: "kb-1",
    organization_id: "org-1",
    owner_user_id: null,
    name: "Handbook",
    description: null,
    scope: "org",
    collection_name: "handbook_a1b2c3",
    is_default: false,
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
    ...overrides,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/secrets") return SECRETS;
    return { items: [], total: 0 };
  });
});

describe("what the panel says", () => {
  it("says reranking is off, and that distance alone orders the results", () => {
    render(<RerankPanel kb={kb()} />, { wrapper });
    expect(screen.getByText(/ordered by vector distance/)).toBeInTheDocument();
  });

  it("names the model and the key when it is on", async () => {
    render(<RerankPanel kb={kb({ rerank_model: "rerank-v3.5", rerank_secret_id: "co-1" })} />, {
      wrapper,
    });
    expect(screen.getByText("rerank-v3.5")).toBeInTheDocument();
    expect(await screen.findByText(/billed to Cohere prod/)).toBeInTheDocument();
  });

  it("falls back to a neutral key label when the reader cannot list secrets", () => {
    // A `collections:edit` holder need not hold `connections:manage`, so
    // `GET /secrets` answers 403 and an empty list - the key's id resolves to no
    // name, and the panel must still say reranking is on rather than break.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    render(<RerankPanel kb={kb({ rerank_model: "rerank-v3.5", rerank_secret_id: "co-1" })} />, {
      wrapper,
    });
    expect(screen.getByText(/billed to a Cohere key/)).toBeInTheDocument();
  });
});

describe("the edit affordance", () => {
  it("offers Edit to a caller who may write", async () => {
    const onEdit = vi.fn();
    render(<RerankPanel kb={kb()} onEdit={onEdit} />, { wrapper });
    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(onEdit).toHaveBeenCalledOnce();
  });

  it("shows no Edit to a caller who may not", () => {
    render(<RerankPanel kb={kb()} />, { wrapper });
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
});
