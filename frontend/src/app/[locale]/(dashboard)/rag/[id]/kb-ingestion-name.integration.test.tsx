import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import KBDetailPage from "./page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { KnowledgeBaseDetail } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), raw: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, isAppAdmin: false }),
}));

const KB_ID = "5eacffcc-873e-42fe-a73a-32cd19322d00";
const COLLECTION_ID = "portable_be9b5d907ba94212b77891601621caca";
const KB: KnowledgeBaseDetail = {
  id: KB_ID,
  name: "Company handbook",
  description: null,
  collection_name: COLLECTION_ID,
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
  created_at: "2026-11-26T12:00:00Z",
  updated_at: null,
  document_count: 0,
  indexed_count: 0,
  chunk_count: 0,
  can_edit: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/");
  useOrgStore.setState({ activeOrgId: "org-1" });
});

it("names ingestion settings for the person while retaining the technical collection and API id", async () => {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === `/kb/${KB_ID}`) return KB;
    if (path === `/kb/${KB_ID}/ingestion`)
      return {
        indexing_status: "complete",
        processing_count: 0,
        indexed_count: 0,
        failed_count: 0,
      };
    return { items: [], total: 0 };
  });
  vi.mocked(apiClient.patch).mockResolvedValue({
    ...KB,
    ingestion_config: { ...DEFAULT_INGESTION_CONFIG, chunk_size: 3000 },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const params = Object.assign(Promise.resolve({ id: KB_ID }), {
    status: "fulfilled",
    value: { id: KB_ID },
  });
  render(
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>
        <KBDetailPage params={params} />
      </Suspense>
    </QueryClientProvider>,
  );
  await act(async () => {
    await params;
  });
  await userEvent.click(await screen.findByRole("button", { name: "Settings" }));
  const dialog = await screen.findByRole("dialog", { name: "Ingestion settings" });
  expect(within(dialog).getByText(KB.name)).toHaveClass("font-medium");
  expect(within(dialog).getByText(KB.name)).not.toHaveClass("font-mono");
  expect(dialog).not.toHaveTextContent(COLLECTION_ID);

  const size = within(dialog).getByRole("spinbutton", { name: "Chunk size" });
  await userEvent.clear(size);
  await userEvent.type(size, "3000");
  await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith(`/kb/${KB_ID}`, {
      ingestion_config: { ...DEFAULT_INGESTION_CONFIG, chunk_size: 3000 },
    }),
  );
  expect(client.getQueryData<KnowledgeBaseDetail>(qk.kb.detail(KB_ID))?.collection_name).toBe(
    COLLECTION_ID,
  );
});
