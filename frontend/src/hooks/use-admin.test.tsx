import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useAdminConversations } from "./use-admin-conversations";
import { useAdminUsers } from "./use-admin-users";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** The path of the nth GET, which is where every filter on these screens ends up. */
function path(nth = 0): string {
  return vi.mocked(apiClient.get).mock.calls[nth]![0] as string;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
});

/**
 * The deployment-admin screens.
 *
 * Both hooks hold their own state rather than using React Query, because these
 * lists are paged, sorted and filtered from the page's own controls and there is
 * nothing to invalidate them from. What is worth pinning is the query string:
 * every filter on the screen has to reach the server, and a dropped one shows a
 * full list under a heading that says it is filtered.
 *
 * `impersonateUser` is the one action here with a security consequence. It hands
 * back a token, and a refusal has to hand back nothing at all rather than an
 * undefined that a caller could treat as success.
 */
describe("useAdminUsers", () => {
  it("pages the list, with the defaults the screen opens on", async () => {
    const { result } = renderHook(() => useAdminUsers());

    await act(() => result.current.fetchUsers());

    expect(path()).toBe("/admin/users?skip=0&limit=50");
  });

  it("carries every filter the screen offers into the request", async () => {
    const { result } = renderHook(() => useAdminUsers());

    await act(() =>
      result.current.fetchUsers({
        skip: 50,
        limit: 25,
        search: "kacper",
        sortBy: "created_at",
        sortDir: "desc",
      }),
    );

    expect(path()).toBe(
      "/admin/users?skip=50&limit=25&search=kacper&sort_by=created_at&sort_dir=desc",
    );
  });

  it("holds the page and the count that pages it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "u-1" }], total: 120 });
    const { result } = renderHook(() => useAdminUsers());

    await act(() => result.current.fetchUsers());

    expect(result.current.users).toHaveLength(1);
    expect(result.current.total).toBe(120);
  });

  it("stops loading whether the read succeeded or not", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("403"));
    const { result } = renderHook(() => useAdminUsers());

    await act(() => result.current.fetchUsers());

    expect(result.current.isLoading).toBe(false);
    expect(toast.error).toHaveBeenCalledWith("Failed to load users");
  });

  it("patches an edited user into the page it is showing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "u-1", is_active: true }],
      total: 1,
    });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "u-1", is_active: false });
    const { result } = renderHook(() => useAdminUsers());
    await act(() => result.current.fetchUsers());

    await act(() => result.current.updateUser("u-1", { is_active: false }));

    expect(apiClient.patch).toHaveBeenCalledWith("/admin/users/u-1", { is_active: false });
    expect(result.current.users[0]).toMatchObject({ is_active: false });
  });

  it("reports a refused edit and leaves the row as it was", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "u-1", is_active: true }],
      total: 1,
    });
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("403"));
    const { result } = renderHook(() => useAdminUsers());
    await act(() => result.current.fetchUsers());

    await act(() => result.current.updateUser("u-1", { is_active: false }));

    expect(toast.error).toHaveBeenCalledWith("Failed to update user");
    expect(result.current.users[0]).toMatchObject({ is_active: true });
  });

  it("drops a deleted user and the count with them", async () => {
    // Otherwise the pager offers a page that is one row shorter than it says.
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "u-1" }, { id: "u-2" }],
      total: 2,
    });
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useAdminUsers());
    await act(() => result.current.fetchUsers());

    await act(() => result.current.deleteUser("u-2"));

    expect(result.current.users.map((user) => user.id)).toEqual(["u-1"]);
    expect(result.current.total).toBe(1);
  });

  it("reports a refused deletion", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("403"));
    const { result } = renderHook(() => useAdminUsers());

    await act(() => result.current.deleteUser("u-1"));

    expect(toast.error).toHaveBeenCalledWith("Failed to delete user");
  });

  it("marks who is being impersonated while the request is in flight", async () => {
    // The row's button is disabled off this, so a request that left it unset would
    // let somebody fire two impersonations at once.
    let release: (value: { access_token: string }) => void = () => {};
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    const { result } = renderHook(() => useAdminUsers());

    const pending = result.current.impersonateUser("u-1");
    await waitFor(() => expect(result.current.impersonating).toBe("u-1"));

    await act(async () => {
      release({ access_token: "imp-token" });
      await pending;
    });

    await expect(pending).resolves.toBe("imp-token");
    expect(apiClient.post).toHaveBeenCalledWith("/admin/users/u-1/impersonate");
    expect(result.current.impersonating).toBeNull();
  });

  it("hands back nothing when impersonation is refused", async () => {
    // Not `undefined`: the caller signs in with whatever comes back, and only an
    // explicit null is safe to branch on.
    vi.mocked(apiClient.post).mockRejectedValue(new Error("403"));
    const { result } = renderHook(() => useAdminUsers());

    let token: string | null | undefined;
    await act(async () => {
      token = await result.current.impersonateUser("u-1");
    });

    expect(token).toBeNull();
    expect(toast.error).toHaveBeenCalledWith("Failed to impersonate user");
    expect(result.current.impersonating).toBeNull();
  });
});

describe("useAdminConversations", () => {
  it("sends only the filters that were set", async () => {
    // A zero skip and an unset search are the same thing to the server, and
    // sending `search=undefined` filters the list to nothing.
    const { result } = renderHook(() => useAdminConversations());

    await act(() => result.current.fetchConversations());

    expect(path()).toBe("/admin/conversations?");
  });

  it("carries every filter the screen offers", async () => {
    const { result } = renderHook(() => useAdminConversations());

    await act(() =>
      result.current.fetchConversations({
        skip: 20,
        limit: 10,
        search: "refund",
        user_id: "u-1",
        agent_id: "a-1",
        status: "archived",
        sort_by: "updated_at",
        sort_dir: "asc",
      }),
    );

    expect(path()).toBe(
      "/admin/conversations?skip=20&limit=10&search=refund&user_id=u-1&agent_id=a-1&status=archived&sort_by=updated_at&sort_dir=asc",
    );
  });

  it("holds the page and its count", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "c-1" }], total: 9 });
    const { result } = renderHook(() => useAdminConversations());

    await act(() => result.current.fetchConversations());

    expect(result.current.conversations).toHaveLength(1);
    expect(result.current.conversationsTotal).toBe(9);
  });

  it("says what the server said when a list is refused", async () => {
    // These screens are behind `is_app_admin`; "Failed to load" would hide the
    // difference between a refusal and an outage.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Forbidden"));
    const { result } = renderHook(() => useAdminConversations());

    await act(() => result.current.fetchConversations());

    expect(result.current.error).toBe("Forbidden");
  });

  it("falls back to its own sentence when the failure carries none", async () => {
    vi.mocked(apiClient.get).mockRejectedValue("boom");
    const { result } = renderHook(() => useAdminConversations());

    await act(() => result.current.fetchConversations());

    expect(result.current.error).toBe("Failed to load conversations");
  });

  it("lists the users who own conversations, with their own filters", async () => {
    const { result } = renderHook(() => useAdminConversations());

    await act(() =>
      result.current.fetchUsers({
        skip: 10,
        limit: 5,
        search: "kacper",
        sort_by: "email",
        sort_dir: "desc",
      }),
    );

    expect(path()).toBe(
      "/admin/conversations/users?skip=10&limit=5&search=kacper&sort_by=email&sort_dir=desc",
    );
  });

  it("sends no filters for the unfiltered user list", async () => {
    const { result } = renderHook(() => useAdminConversations());

    await act(() => result.current.fetchUsers());

    expect(path()).toBe("/admin/conversations/users?");
  });

  it("holds the users and their count", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "u-1" }], total: 3 });
    const { result } = renderHook(() => useAdminConversations());

    await act(() => result.current.fetchUsers());

    expect(result.current.users).toHaveLength(1);
    expect(result.current.usersTotal).toBe(3);
  });

  it("reports a refused user list", async () => {
    vi.mocked(apiClient.get).mockRejectedValue("boom");
    const { result } = renderHook(() => useAdminConversations());

    await act(() => result.current.fetchUsers());

    expect(result.current.error).toBe("Failed to load users");
  });

  it("opens one conversation, and hands it back as well as holding it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "c-1", messages: [] });
    const { result } = renderHook(() => useAdminConversations());

    let opened: unknown;
    await act(async () => {
      opened = await result.current.fetchConversationDetail("c-1");
    });

    expect(apiClient.get).toHaveBeenCalledWith("/admin/conversations/c-1");
    expect(opened).toMatchObject({ id: "c-1" });
    expect(result.current.selectedConversation).toMatchObject({ id: "c-1" });
  });

  it("hands back nothing for a conversation it could not read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue("boom");
    const { result } = renderHook(() => useAdminConversations());

    let opened: unknown;
    await act(async () => {
      opened = await result.current.fetchConversationDetail("c-1");
    });

    expect(opened).toBeNull();
    expect(result.current.error).toBe("Failed to load conversation");
  });

  it("closes the opened conversation when the drawer is dismissed", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "c-1", messages: [] });
    const { result } = renderHook(() => useAdminConversations());
    await act(async () => {
      await result.current.fetchConversationDetail("c-1");
    });

    act(() => result.current.setSelectedConversation(null));

    expect(result.current.selectedConversation).toBeNull();
  });

  it("stays loading until the last of several reads finishes", async () => {
    // The page fires the conversation list and the user list together. A single
    // boolean would let the first to return switch the spinner off while the
    // other is still in flight, and the table would render half-empty.
    const resolvers: ((value: unknown) => void)[] = [];
    vi.mocked(apiClient.get).mockImplementation(
      () => new Promise((resolve) => resolvers.push(resolve)),
    );
    const { result } = renderHook(() => useAdminConversations());

    const both = Promise.all([result.current.fetchConversations(), result.current.fetchUsers()]);
    await waitFor(() => expect(resolvers).toHaveLength(2));
    await waitFor(() => expect(result.current.isLoading).toBe(true));

    await act(async () => {
      resolvers[0]!({ items: [], total: 0 });
      await Promise.resolve();
    });
    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      resolvers[1]!({ items: [], total: 0 });
      await both;
    });
    expect(result.current.isLoading).toBe(false);
  });
});
