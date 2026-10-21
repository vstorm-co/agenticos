import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KBDetailPage from "./page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import { useOrgStore } from "@/stores";
import type { KnowledgeBase } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), raw: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const perms = new Set<string>();
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (p: string) => perms.has(p) }),
}));

const KB_ID = "5eacffcc-873e-42fe-a73a-32cd19322d00";

const KB: KnowledgeBase = {
  id: KB_ID,
  name: "Handbook",
  description: null,
  collection_name: "handbook",
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
};

const TOPIC = {
  id: "t1",
  knowledge_base_id: KB_ID,
  knowledge_base_name: "Handbook",
  status: "open",
  label: "How long is parental leave?",
  question_count: 4,
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [
    { id: "a1", name: "HR helper", slug: "hr-helper", has_avatar: false, avatar_color: null },
  ],
  dismissed_at: null,
  has_draft: false,
  can_edit: false,
};

function mockApi({ canEdit = false } = {}) {
  const topic = { ...TOPIC, can_edit: canEdit };
  vi.mocked(apiClient.get).mockImplementation((endpoint: string) => {
    if (endpoint === `/kb/${KB_ID}`) return Promise.resolve(KB);
    if (endpoint.startsWith(`/knowledge-gaps/collections/${KB_ID}`)) {
      return Promise.resolve({ items: [topic], total: 1, ungrouped: 0, can_regroup: canEdit });
    }
    if (endpoint === "/knowledge-gaps/t1") return Promise.resolve({ ...topic, questions: [] });
    return Promise.resolve({ items: [], total: 0 });
  });
}

function fulfilled<T>(value: T): Promise<T> {
  const thenable = Promise.resolve(value) as Promise<T> & { status: string; value: T };
  thenable.status = "fulfilled";
  thenable.value = value;
  return thenable;
}

async function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>
        <KBDetailPage params={fulfilled({ id: KB_ID })} />
      </Suspense>
    </QueryClientProvider>,
  );
  await act(async () => {});
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  vi.clearAllMocks();
  perms.clear();
  useOrgStore.setState({ activeOrgId: "org-1" });
  mockApi();
});

describe("the knowledge gaps tab on a collection", () => {
  it("is not there for a caller who may not read runs, and nothing asks for gaps", async () => {
    perms.add("collections:view");
    await renderPage();
    await screen.findByRole("tab", { name: "Documents" });

    expect(screen.queryByRole("tab", { name: "Knowledge gaps" })).toBeNull();
    expect(document.querySelector('[data-tour="kb-tab-gaps"]')).toBeNull();
    expect(vi.mocked(apiClient.get).mock.calls.map(([url]) => url)).not.toContainEqual(
      expect.stringContaining("/knowledge-gaps"),
    );
  });

  it("lists the collection's topics for a caller who reads runs, without Dismiss unless they edit it", async () => {
    perms.add("collections:view").add("runs:view");
    await renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Knowledge gaps" }));

    expect(await screen.findByText("How long is parental leave?")).toBeInTheDocument();
    expect(document.querySelector('[data-tour="kb-gaps"]')).not.toBeNull();
    expect(apiClient.get).toHaveBeenCalledWith(
      `/knowledge-gaps/collections/${KB_ID}?status=open&skip=0&limit=50`,
    );
    expect(screen.queryByRole("button", { name: /group now/i })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /parental leave/ }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/knowledge-gaps/t1"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More actions for this topic" })).toBeNull();
  });

  it("offers grouping now and Dismiss to a caller the collection lets edit it", async () => {
    perms.add("collections:view").add("runs:view");
    mockApi({ canEdit: true });
    vi.mocked(apiClient.post).mockResolvedValue({ ...TOPIC, status: "dismissed", questions: [] });
    await renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Knowledge gaps" }));

    expect(await screen.findByRole("button", { name: /group now/i })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /parental leave/ }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "More actions for this topic",
      }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: "Dismiss" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/knowledge-gaps/t1/dismiss"));
  });
});
