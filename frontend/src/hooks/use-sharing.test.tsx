import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSharing } from "./use-sharing";
import { apiClient } from "@/lib/api-client";
import type { ResourceSharing } from "@/types/sharing";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SHARING: ResourceSharing = {
  resource_type: "agent",
  resource_id: "a1",
  owner_user_id: "u-owner",
  visibility: "private",
  grants: [
    {
      id: "g1",
      subject_user_id: "u-sam",
      subject_email: "sam@example.com",
      resource_type: "agent",
      resource_id: "a1",
      level: "read",
    },
  ],
};

describe("useSharing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(SHARING);
  });

  it("reads who reaches the resource", async () => {
    const { result } = renderHook(() => useSharing("agent", "a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/sharing");
    expect(result.current.sharing?.grants[0]?.subject_email).toBe("sam@example.com");
  });

  it("addresses each resource type at its own endpoints", async () => {
    // The same four routes exist per type. A panel hardcoded to agents is how
    // sharing a skill silently edits an agent with a colliding id.
    const { result } = renderHook(() => useSharing("skill", "s1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/sharing");

    vi.mocked(apiClient.put).mockResolvedValue({});
    await result.current.share.mutateAsync({ subject_user_id: "u-sam", level: "use" });
    expect(apiClient.put).toHaveBeenCalledWith("/skills/s1/sharing/grants", {
      subject_user_id: "u-sam",
      level: "use",
    });
  });

  it("does not fetch until a resource is selected", () => {
    renderHook(() => useSharing("agent", null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("sends the whole grant when sharing, so a level change is the same call", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({});
    const { result } = renderHook(() => useSharing("agent", "a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.share.mutateAsync({ subject_user_id: "u-sam", level: "edit" });

    expect(apiClient.put).toHaveBeenCalledWith("/agents/a1/sharing/grants", {
      subject_user_id: "u-sam",
      level: "edit",
    });
  });

  it("revokes by subject, then re-reads rather than trusting its own guess", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useSharing("agent", "a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.revoke.mutateAsync("u-sam");

    expect(apiClient.delete).toHaveBeenCalledWith("/agents/a1/sharing/grants/u-sam");
    // Visibility and the grant list move together on the server; refetching is
    // what keeps the panel from showing a share that no longer exists.
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });

  it("changes visibility and re-reads the sharing state it affects", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ ...SHARING, visibility: "org" });
    const { result } = renderHook(() => useSharing("agent", "a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.setVisibility.mutateAsync("org");

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/sharing/visibility", {
      visibility: "org",
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });

  it("surfaces the server's refusal instead of leaving the panel silent", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.put).mockRejectedValue(new Error("You cannot change sharing"));
    const { result } = renderHook(() => useSharing("agent", "a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(
      result.current.share.mutateAsync({ subject_user_id: "u-sam", level: "read" }),
    ).rejects.toThrow("You cannot change sharing");
    expect(toast.error).toHaveBeenCalledWith("You cannot change sharing");
  });
});
