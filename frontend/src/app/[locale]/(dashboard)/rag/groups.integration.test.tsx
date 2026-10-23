import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RAGPage from "./page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import { useOrgStore } from "@/stores";
import type { KnowledgeBase } from "@/types";

/**
 * Knowledge bases grouped by department (#2124).
 *
 * A group is already who a base reaches, so the page is grouped by narrowing it
 * to the bases one group was given - the list arrives whole, so it narrows here.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (p: string) => p === "collections:view" }),
}));
const searchParams = vi.hoisted(() => ({ current: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams.current,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/rag",
}));

function kb(id: string, name: string, groups: string[]): KnowledgeBase {
  return {
    id,
    name,
    description: null,
    collection_name: id,
    scope: "org",
    organization_id: "org-1",
    owner_user_id: null,
    is_default: false,
    ingestion_config: DEFAULT_INGESTION_CONFIG,
    embedding_model: "text-embedding-3-large",
    embedding_provider: "openrouter",
    embedding_secret_id: null,
    embedding_endpoint_id: null,
    embedding_dim: 3072,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    document_count: 0,
    indexed_count: 0,
    chunk_count: 0,
    shared_groups: groups,
  };
}

function answer(groups: { id: string; name: string }[]) {
  vi.mocked(apiClient.get).mockImplementation((endpoint: string) => {
    if (endpoint === "/kb") {
      const items = [kb("kb-1", "Invoices", ["Finance"]), kb("kb-2", "Calls", ["Sales"])];
      return Promise.resolve({ items, total: items.length });
    }
    if (endpoint === "/orgs/org-1/groups") {
      const items = groups.map((group) => ({
        ...group,
        organization_id: "org-1",
        description: null,
        icon: null,
        monthly_budget_usd: null,
        member_count: 1,
        created_at: "2026-10-13T00:00:00Z",
      }));
      return Promise.resolve({ items, total: items.length });
    }
    // The create dialog renders straight from the provider list.
    if (endpoint === "/rag/embedding-models") return Promise.resolve({ providers: [] });
    return Promise.resolve({ items: [], total: 0 });
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const FINANCE = { id: "g-fin", name: "Finance" };
const OPS = { id: "g-ops", name: "Ops" };

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org-1" });
  searchParams.current = new URLSearchParams();
});

describe("knowledge bases grouped by department", () => {
  it("lists every base until a group is chosen, then only what that group was given", async () => {
    answer([FINANCE, OPS]);
    render(<RAGPage />, { wrapper });
    expect(await screen.findByText("Calls")).toBeInTheDocument();

    await userEvent.click(await screen.findByRole("combobox", { name: "Filter by group" }));
    await userEvent.click(screen.getByRole("option", { name: "Finance" }));

    await waitFor(() => expect(screen.queryByText("Calls")).toBeNull());
    expect(screen.getByText("Invoices")).toBeInTheDocument();
    expect(window.location.search).toContain("group=g-fin");
  });

  it("says a group was given nothing rather than that there are no bases", async () => {
    searchParams.current = new URLSearchParams("group=g-ops");
    answer([FINANCE, OPS]);
    render(<RAGPage />, { wrapper });

    expect(await screen.findByText("Nothing here is shared with Ops yet")).toBeInTheDocument();
    expect(screen.queryByText("Invoices")).toBeNull();
  });
});
