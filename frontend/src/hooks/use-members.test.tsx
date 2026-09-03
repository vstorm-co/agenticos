import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMembers } from "./use-members";
import { apiClient } from "@/lib/api-client";
import type { OrganizationMember } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function member(index: number): OrganizationMember {
  return {
    id: `m-${index}`,
    user_id: `u-${index}`,
    organization_id: "org-1",
    role: "member",
    email: `person-${index}@example.com`,
    full_name: `Person ${index}`,
    avatar_url: null,
    avatar_color: null,
    joined_at: "2026-07-01T00:00:00Z",
  };
}

/** `skip` off the URL a call was made with, so a page can be identified. */
function skips() {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([url]) => new URL(url, "http://x").searchParams.get("skip"));
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
});

/**
 * Every member, not the first page of them.
 *
 * The route defaults to fifty and caps at a hundred. The share dialog's picker
 * is the only way to name somebody since the email field was removed, and it
 * offers exactly what this hook returns - so a member on the second page could
 * not be shared with at all, and could not be found by typing either, because
 * the filter runs over what was fetched (#1335).
 */
describe("useMembers", () => {
  it("keeps asking until a page comes back short", async () => {
    const first = Array.from({ length: 100 }, (_, index) => member(index));
    const second = Array.from({ length: 10 }, (_, index) => member(100 + index));
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: first, total: 110 })
      .mockResolvedValueOnce({ items: second, total: 110 });

    const { result } = renderHook(() => useMembers("org-1"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(skips()).toEqual(["0", "100"]);
    expect(result.current.members).toHaveLength(110);
    // The one the picker could not offer.
    expect(result.current.members.at(-1)?.email).toBe("person-109@example.com");
  });

  it("stops on a short first page rather than asking for a second", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [member(0)], total: 1 });

    const { result } = renderHook(() => useMembers("org-1"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("ends on the short page rather than on the count the server claims", async () => {
    // A `total` that disagrees with what was served - a member removed between
    // two pages - would loop forever if the count decided when to stop.
    const full = Array.from({ length: 100 }, (_, index) => member(index));
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: full, total: 500 })
      .mockResolvedValueOnce({ items: [], total: 500 });

    const { result } = renderHook(() => useMembers("org-1"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(result.current.members).toHaveLength(100);
    // Reported as the server states it, even where it disagrees: the count is
    // the server's claim and this hook does not correct it.
    expect(result.current.total).toBe(500);
  });

  it("asks for nothing without an organization", () => {
    renderHook(() => useMembers(""), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
