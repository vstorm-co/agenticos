import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useServiceConnections } from "./use-service-connections";
import * as api from "@/lib/service-connections-api";
import type { ServiceConnectionRecord } from "@/lib/service-connections-api";

vi.mock("@/lib/service-connections-api", () => ({
  listServiceConnections: vi.fn(),
  createServiceConnection: vi.fn(),
  updateServiceConnection: vi.fn(),
  deleteServiceConnection: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function service(overrides: Partial<ServiceConnectionRecord> = {}): ServiceConnectionRecord {
  return {
    id: "ls-1",
    organization_id: "org-1",
    kind: "embedding",
    provider: "ollama",
    name: "GPU box",
    base_url: "http://ollama:11434/v1",
    is_active: true,
    secret_id: null,
    requires_key: false,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listServiceConnections).mockResolvedValue([service()]);
  vi.mocked(api.createServiceConnection).mockResolvedValue(service({ id: "ls-2" }));
  vi.mocked(api.updateServiceConnection).mockResolvedValue(service({ is_active: false }));
  vi.mocked(api.deleteServiceConnection).mockResolvedValue(undefined);
});

describe("useServiceConnections", () => {
  it("lists what the organization may reach", async () => {
    const { result } = renderHook(() => useServiceConnections(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.connections).toEqual([service()]);
    expect(result.current.error).toBeNull();
  });

  it("asks for nothing while disabled, and reports no loading", () => {
    const { result } = renderHook(() => useServiceConnections(false), { wrapper });

    expect(api.listServiceConnections).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.connections).toEqual([]);
  });

  it("refetches the list after each write, so a picker sees the new row", async () => {
    const { result } = renderHook(() => useServiceConnections(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      const created = await result.current.create({
        name: "OCR",
        kind: "ocr",
        provider: "liteparse",
        base_url: "http://ocr:8000",
      });
      expect(created.id).toBe("ls-2");
    });
    await act(async () => {
      const updated = await result.current.update("ls-1", { is_active: false });
      expect(updated.is_active).toBe(false);
    });
    await act(async () => {
      await result.current.remove("ls-1");
    });

    expect(api.deleteServiceConnection).toHaveBeenCalledWith("ls-1");
    // The initial read plus one per write.
    await waitFor(() => expect(api.listServiceConnections).toHaveBeenCalledTimes(4));
  });

  it("says when the list could not be read", async () => {
    vi.mocked(api.listServiceConnections).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useServiceConnections(), { wrapper });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.connections).toEqual([]);
  });
});
