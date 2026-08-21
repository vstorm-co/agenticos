import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useAdminUsers } from "./use-admin-users";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

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

  it("stops loading and surfaces a failed read inline, not as a toast", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("403"));
    const { result } = renderHook(() => useAdminUsers());

    await act(() => result.current.fetchUsers());

    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe("Failed to load users");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("forgets a failure once a later read succeeds", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("502"));
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useAdminUsers());

    await act(() => result.current.fetchUsers());
    await act(() => result.current.fetchUsers());

    expect(result.current.error).toBeNull();
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

  it("surfaces the backend's reason when a deletion is refused (#941)", async () => {
    // Deleting your own row is refused with an explanation; the admin should see
    // it, not a generic "failed" that reads as a transient error.
    vi.mocked(apiClient.delete).mockRejectedValue(
      new ApiError(403, "You cannot delete your own account; ask another app admin to.", {
        error: { code: "AUTHORIZATION_ERROR" },
      }),
    );
    const { result } = renderHook(() => useAdminUsers());

    await act(() => result.current.deleteUser("u-1"));

    expect(toast.error).toHaveBeenCalledWith(
      "You cannot delete your own account; ask another app admin to.",
    );
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
