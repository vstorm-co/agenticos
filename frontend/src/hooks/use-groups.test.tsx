import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useAddDepartments,
  useGroupMembers,
  useGroupResources,
  useGroupSharing,
  useGroupSpend,
  useGroups,
} from "./use-groups";
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

describe("useGroupResources", () => {
  it("reads what was shared with the group", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ kind: "skill", id: "s1", name: "ledger", level: "use" }],
      total: 1,
    });
    const { result } = renderHook(() => useGroupResources("o-1", "g-1"), { wrapper });

    await waitFor(() => expect(result.current.resources).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/resources");
  });
});

describe("a group's lead and what it is given (#2072)", () => {
  it("names a lead, and says why when refused", async () => {
    vi.mocked(apiClient.patch).mockResolvedValueOnce({ ...ROW, is_lead: true });
    const { result } = renderHook(() => useGroupMembers("o-1", "g-1"), { wrapper });

    await act(async () => {
      await result.current.setLead.mutateAsync({ userId: "u-1", isLead: true });
    });
    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/members/u-1", {
      is_lead: true,
    });
    expect(toast.success).toHaveBeenCalledWith("Lead updated");

    vi.mocked(apiClient.patch).mockRejectedValueOnce(new ApiError(403, "Admins only"));
    await act(async () => {
      await result.current.setLead
        .mutateAsync({ userId: "u-1", isLead: false })
        .catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalledWith("Admins only");
  });

  it("offers what can be shared and shares several at once", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ kind: "skill", id: "s1", name: "ledger", level: "use" }],
      total: 1,
    });
    vi.mocked(apiClient.post).mockResolvedValue(undefined);
    const { result } = renderHook(() => useGroupSharing("o-1", "g-1"), { wrapper });

    await waitFor(() => expect(result.current.shareable).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/shareable");
    await act(async () => {
      await result.current.share.mutateAsync({
        items: [{ kind: "skill", id: "s1" }],
        level: "use",
      });
    });
    expect(apiClient.post).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/shares", {
      items: [{ kind: "skill", id: "s1" }],
      level: "use",
    });
    expect(toast.success).toHaveBeenCalledWith("Shared 1 item with the group");

    vi.mocked(apiClient.post).mockRejectedValueOnce(new ApiError(403, "Cannot edit that"));
    await act(async () => {
      await result.current.share
        .mutateAsync({ items: [{ kind: "skill", id: "s1" }], level: "use" })
        .catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalledWith("Cannot edit that");
  });
});

describe("useGroupSpend", () => {
  it("reads the month when it may, and asks nothing when it may not (#2072)", async () => {
    const month = { since: "2026-10-01T00:00:00Z", items: [] };
    vi.mocked(apiClient.get).mockResolvedValue(month);

    const allowed = renderHook(() => useGroupSpend("o-1"), { wrapper });
    await waitFor(() => expect(allowed.result.current.spend).toEqual(month));
    renderHook(() => useGroupSpend("o-1", false), { wrapper });
    renderHook(() => useGroupSpend(null), { wrapper });

    expect(apiClient.get).toHaveBeenCalledTimes(1);
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/groups/spend");
  });
});

describe("useAddDepartments", () => {
  it("creates each department in turn and says how many", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(GROUP);
    const { result } = renderHook(() => useAddDepartments("o-1"), { wrapper });

    await act(async () => {
      await result.current.mutateAsync([
        { name: "Sales", description: null, icon: "briefcase" },
        { name: "Finance", description: null, icon: "banknote" },
      ]);
    });

    expect(apiClient.post).toHaveBeenCalledTimes(2);
    expect(toast.success).toHaveBeenCalledWith("Added 2 departments");
  });

  it("stops at a refused one and says why", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(409, "Taken"));
    const { result } = renderHook(() => useAddDepartments("o-1"), { wrapper });

    await act(async () => {
      await result.current
        .mutateAsync([
          { name: "Sales", description: null },
          { name: "HR", description: null },
        ])
        .catch(() => undefined);
    });

    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith("Taken");
  });
});
