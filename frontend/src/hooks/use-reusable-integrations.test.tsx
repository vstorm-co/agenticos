import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useReusableIntegrations } from "./use-reusable-integrations";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { SyncSourceRead } from "@/lib/rag-api";
import type { KnowledgeBase } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ORG_ID = "org-1";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function source(overrides: Partial<SyncSourceRead> = {}): SyncSourceRead {
  return {
    id: "s1",
    organization_id: ORG_ID,
    name: "Handbook drive",
    connector_type: "gdrive",
    collection_name: null,
    config: { folder_id: "abc" },
    sync_mode: "full",
    schedule_minutes: null,
    is_active: true,
    last_sync_at: null,
    last_sync_status: null,
    last_error: null,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

const TARGET: KnowledgeBase = {
  id: "kb-1",
  name: "Handbook",
  description: null,
  collection_name: "handbook_a1b2c3",
  scope: "org",
  organization_id: ORG_ID,
  owner_user_id: null,
  is_default: false,
  ingestion_config: DEFAULT_INGESTION_CONFIG,
  embedding_model: "text-embedding-3-large",
  embedding_dim: 3072,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: null,
};

/** Answer each GET with the list it asked for; anything else is a mistake. */
function serve(items: SyncSourceRead[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === `/orgs/${ORG_ID}/integrations`) return { items, total: items.length };
    if (path === `/orgs/${ORG_ID}/integrations/connectors`) return { items: [] };
    throw new Error(`unexpected GET ${path}`);
  });
}

async function loaded(items: SyncSourceRead[] = [source()]) {
  serve(items);
  const hook = renderHook(() => useReusableIntegrations(ORG_ID), { wrapper });
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
  return hook;
}

describe("useReusableIntegrations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps only the integrations no collection owns", async () => {
    // The endpoint answers with the organization's whole set. The assigned rows
    // are shown by the collection they feed; repeating them here is the
    // duplication this surface exists to end.
    const { result } = await loaded([source(), source({ id: "s2", collection_name: "handbook" })]);

    expect(result.current.integrations.map((entry) => entry.id)).toEqual(["s1"]);
  });

  it("asks for nothing at all without an organization", async () => {
    // The endpoint is owner/admin-only. A member is shown no section, so the
    // section must also collect no 403.
    serve([]);
    renderHook(() => useReusableIntegrations(null), { wrapper });

    await waitFor(() => expect(apiClient.get).not.toHaveBeenCalled());
  });

  it("creates an integration that belongs to no collection", async () => {
    // `collection_name` decides the whole nature of the row: with one it is a
    // sync source for a single base, without one it is the thing several bases
    // are cloned from.
    vi.mocked(apiClient.post).mockResolvedValue(source({ id: "s9" }));
    const { result } = await loaded([]);

    await act(async () => {
      await result.current.create({
        name: "Handbook drive",
        connector_type: "gdrive",
        config: { folder_id: "abc" },
        collection_name: "handbook_a1b2c3",
      });
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      `/orgs/${ORG_ID}/integrations`,
      expect.objectContaining({ collection_name: null }),
    );
    await waitFor(() =>
      expect(result.current.integrations.map((entry) => entry.id)).toEqual(["s9"]),
    );
  });

  it("hands a rejected configuration back to the caller", async () => {
    // The connector validates the config server-side, and its refusal names the
    // field. Swallowing it here would close the wizard on the step holding the
    // answer and leave the reader with a list that did not grow.
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Invalid connector config: bucket"));
    const { result } = await loaded([]);

    await expect(
      result.current.create({ name: "S3", connector_type: "s3", config: {} }),
    ).rejects.toThrow("Invalid connector config: bucket");
    expect(result.current.integrations).toEqual([]);
  });

  it("clones through the destination knowledge base and keeps the original", async () => {
    // Two things at once: the clone goes to the route that resolves the origin
    // inside the caller's organization, and the row stays on the list - an
    // integration usable once would not be reusable.
    vi.mocked(apiClient.post).mockResolvedValue(source({ id: "s2", collection_name: "handbook" }));
    const { result } = await loaded();

    await act(async () => {
      await result.current.cloneInto("s1", TARGET, "Handbook drive (Handbook)");
    });

    expect(apiClient.post).toHaveBeenCalledWith("/kb/kb-1/sync-sources/s1/clone", {
      collection_name: "handbook_a1b2c3",
      name: "Handbook drive (Handbook)",
    });
    expect(result.current.integrations.map((entry) => entry.id)).toEqual(["s1"]);
  });

  it("drops a removed integration without a refetch", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = await loaded();

    await act(async () => {
      await result.current.remove("s1");
    });

    await waitFor(() => expect(result.current.integrations).toEqual([]));
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("reports a refusal rather than an organization with nothing configured", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Insufficient permissions"));
    const { result } = renderHook(() => useReusableIntegrations(ORG_ID), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Insufficient permissions"));
    expect(result.current.integrations).toEqual([]);
  });
});
