import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAdminOrganizations } from "./use-admin-organizations";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
});

const params = () => vi.mocked(apiClient.get).mock.lastCall?.[1] as { params: object };

/**
 * Every tenant on the deployment - the admin list and the top-organizations
 * card, through one hook.
 *
 * The request is what is worth pinning: a narrowing dropped on the way to the
 * server shows an unfiltered list under a heading that says it is filtered, and
 * a sort dropped shows fifty arbitrary rows claiming to be the largest.
 */
describe("useAdminOrganizations", () => {
  it("asks for one server page and nothing else, by default", async () => {
    const { result } = renderHook(() => useAdminOrganizations(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/admin/organizations", {
      params: { limit: "50" },
    });
  });

  it("carries every narrowing the screen offers", async () => {
    renderHook(
      () =>
        useAdminOrganizations({
          skip: 50,
          limit: 25,
          search: "acme",
          sortBy: "members",
          sortDir: "asc",
          kind: "team",
        }),
      { wrapper },
    );

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(params().params).toEqual({
      skip: "50",
      limit: "25",
      search: "acme",
      sort_by: "members",
      sort_dir: "asc",
      kind: "team",
    });
  });

  it("leaves an unnarrowed request unnarrowed", async () => {
    // `all` is the absence of a filter rather than a value, like the run
    // filters: a request carries only what it actually narrows.
    renderHook(() => useAdminOrganizations({ kind: "all", search: "", skip: 0 }), { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(params().params).toEqual({ limit: "50" });
  });

  it("asks again when a narrowing changes, rather than answering from the last one", async () => {
    // The card asks for five and this page for fifty of whatever it is narrowed
    // to. Under one bare key whichever mounted first filled the cache and the
    // other rendered its answer.
    const { rerender } = renderHook(({ search }) => useAdminOrganizations({ search }), {
      wrapper,
      initialProps: { search: "acme" },
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));

    rerender({ search: "initech" });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(params().params).toEqual({ limit: "50", search: "initech" });
  });

  it("holds the page and the count that pages it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "o1" }], total: 137 });
    const { result } = renderHook(() => useAdminOrganizations(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.organizations).toHaveLength(1);
    expect(result.current.total).toBe(137);
  });

  it("does not fetch for a caller who is not the app admin", () => {
    renderHook(() => useAdminOrganizations({}, { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
