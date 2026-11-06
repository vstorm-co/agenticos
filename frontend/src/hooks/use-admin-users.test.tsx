import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAdminUsers } from "./use-admin-users";
import { apiClient } from "@/lib/api-client";
import type { AdminUserListResponse } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/hooks/use-auth", () => ({ useReauthenticate: () => vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe("admin user loading", () => {
  it("starts pending, then accepts only the most recently requested page", async () => {
    let first: (value: AdminUserListResponse) => void = () => {};
    let second: (value: AdminUserListResponse) => void = () => {};
    vi.mocked(apiClient.get)
      .mockReturnValueOnce(
        new Promise<AdminUserListResponse>((resolve) => {
          first = resolve;
        }),
      )
      .mockReturnValueOnce(
        new Promise<AdminUserListResponse>((resolve) => {
          second = resolve;
        }),
      );
    const { result, unmount } = renderHook(() => useAdminUsers());
    expect(result.current.isLoading).toBe(true);
    let older: Promise<void>;
    let newer: Promise<void>;
    act(() => {
      older = result.current.fetchUsers({ search: "first" });
      newer = result.current.fetchUsers({ search: "second" });
    });
    await act(async () => {
      second({ items: [], total: 2 });
      await newer;
    });
    expect(result.current.total).toBe(2);
    expect(result.current.isLoading).toBe(false);
    await act(async () => {
      first({ items: [], total: 99 });
      await older;
    });
    expect(result.current.total).toBe(2);
    await waitFor(() => expect(result.current.error).toBeNull());
    unmount();
  });
});
