import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useGroupMembers, useGroups } from "./use-groups";
import { apiClient, ApiError } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const GROUP = {
  id: "g-1",
  organization_id: "o-1",
  name: "Finance",
  description: null,
  member_count: 1,
  created_at: "2026-09-01T00:00:00Z",
};
const ROW = {
  user_id: "u-1",
  email: "a@acme.test",
  full_name: null,
  source: "manual",
  created_at: "2026-09-01T00:00:00Z",
};

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  vi.mocked(apiClient.get).mockImplementation((url: string) =>
    Promise.resolve(url.endsWith("/members") ? { items: [ROW], total: 1 } : { items: [GROUP] }),
  );
});

describe("useGroups", () => {
  it("reads the organization in the path", async () => {
    const { result } = renderHook(() => useGroups("o-1"), { wrapper });

    await waitFor(() => expect(result.current.groups).toEqual([GROUP]));
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/groups");
  });

  it("asks nothing before there is an organization to ask about", () => {
    const { result } = renderHook(() => useGroups(""), { wrapper });

    expect(result.current.groups).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("refetches the list after a create and a rename, and says so", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(GROUP);
    vi.mocked(apiClient.patch).mockResolvedValue(GROUP);
    const { result } = renderHook(() => useGroups("o-1"), { wrapper });
    await waitFor(() => expect(result.current.groups).toHaveLength(1));
    vi.mocked(apiClient.get).mockClear();

    await act(async () => {
      await result.current.create.mutateAsync({ name: "Finance", description: null });
    });
    await act(async () => {
      await result.current.update.mutateAsync({ groupId: "g-1", input: { name: "Money" } });
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/o-1/groups/g-1", { name: "Money" });
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(toast.success).toHaveBeenCalledWith("Group created");
    expect(toast.success).toHaveBeenCalledWith("Group saved");
  });

  it("leaves a refused create to the dialog that made it", async () => {
    // A taken name belongs under the name field; a toast as well would say it twice.
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(409, "Name taken"));
    const { result } = renderHook(() => useGroups("o-1"), { wrapper });

    await act(async () => {
      await expect(
        result.current.create.mutateAsync({ name: "Finance", description: null }),
      ).rejects.toThrow("Name taken");
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("marks the grants and mappings a deleted group took with it as stale", async () => {
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useGroups("o-1"), { wrapper });

    await act(async () => {
      await result.current.remove.mutateAsync("g-1");
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/orgs/o-1/groups/g-1");
    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toContainEqual(qk.organizations.directoryMappings("o-1"));
    expect(keys).toContainEqual(qk.sharing.all());
    expect(toast.success).toHaveBeenCalledWith("Group deleted");
  });

  it("says why a delete was refused", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new ApiError(403, "Not allowed"));
    const { result } = renderHook(() => useGroups("o-1"), { wrapper });

    await act(async () => {
      await result.current.remove.mutateAsync("g-1").catch(() => undefined);
    });

    expect(toast.error).toHaveBeenCalledWith("Not allowed");
  });
});

describe("useGroupMembers", () => {
  it("reads one group's members", async () => {
    const { result } = renderHook(() => useGroupMembers("o-1", "g-1"), { wrapper });

    await waitFor(() => expect(result.current.members).toEqual([ROW]));
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/members");
  });

  it("adds and removes somebody, refreshing the groups their count lives on", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(ROW);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useGroupMembers("o-1", "g-1"), { wrapper });

    await act(async () => {
      await result.current.add.mutateAsync("u-2");
    });
    await act(async () => {
      await result.current.remove.mutateAsync("u-1");
    });

    expect(apiClient.post).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/members", {
      user_id: "u-2",
    });
    expect(apiClient.delete).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/members/u-1");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.organizations.groups("o-1") });
    expect(toast.success).toHaveBeenCalledWith("Added to the group");
    expect(toast.success).toHaveBeenCalledWith("Removed from the group");
  });

  it("says why an add or a removal was refused", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(400, "Not a member here"));
    vi.mocked(apiClient.delete).mockRejectedValue(new ApiError(403, "Not allowed"));
    const { result } = renderHook(() => useGroupMembers("o-1", "g-1"), { wrapper });

    await act(async () => {
      await result.current.add.mutateAsync("u-9").catch(() => undefined);
    });
    await act(async () => {
      await result.current.remove.mutateAsync("u-1").catch(() => undefined);
    });

    expect(toast.error).toHaveBeenCalledWith("Not a member here");
    expect(toast.error).toHaveBeenCalledWith("Not allowed");
  });
});
