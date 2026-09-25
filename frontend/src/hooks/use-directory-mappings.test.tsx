import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDirectoryMappings } from "./use-directory-mappings";
import { apiClient, ApiError } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const MAPPING = {
  id: "m-1",
  organization_id: "o-1",
  external_group: "cn=finance,ou=groups,dc=acme,dc=test",
  role: "member",
  group_id: null,
  group_name: null,
  created_at: "2026-09-01T00:00:00Z",
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [MAPPING], total: 1 });
});

describe("useDirectoryMappings", () => {
  it("reads the organization's mappings when the caller may", async () => {
    const { result } = renderHook(() => useDirectoryMappings("o-1", true), { wrapper });

    await waitFor(() => expect(result.current.mappings).toEqual([MAPPING]));
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/directory-mappings");
  });

  it("asks nothing of a caller the server would refuse", () => {
    // A refusal rendered as an empty table is a list of mappings that is not true.
    const { result } = renderHook(() => useDirectoryMappings("o-1", false), { wrapper });

    expect(result.current.mappings).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("adds a mapping, refetches the list and says so", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(MAPPING);
    const { result } = renderHook(() => useDirectoryMappings("o-1", true), { wrapper });
    await waitFor(() => expect(result.current.mappings).toHaveLength(1));

    await act(async () => {
      await result.current.create.mutateAsync({
        external_group: "cn=ops,dc=acme,dc=test",
        role: "operator",
        group_id: "g-1",
      });
    });

    expect(apiClient.post).toHaveBeenCalledWith("/orgs/o-1/directory-mappings", {
      external_group: "cn=ops,dc=acme,dc=test",
      role: "operator",
      group_id: "g-1",
    });
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(toast.success).toHaveBeenCalledWith("Mapping added");
  });

  it("deletes a mapping, and says why when that is refused", async () => {
    const { result } = renderHook(() => useDirectoryMappings("o-1", true), { wrapper });

    await act(async () => {
      await result.current.remove.mutateAsync("m-1");
    });
    expect(apiClient.delete).toHaveBeenCalledWith("/orgs/o-1/directory-mappings/m-1");
    expect(toast.success).toHaveBeenCalledWith("Mapping deleted");

    vi.mocked(apiClient.delete).mockRejectedValue(new ApiError(403, "Outranked"));
    await act(async () => {
      await result.current.remove.mutateAsync("m-1").catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalledWith("Outranked");
  });
});
