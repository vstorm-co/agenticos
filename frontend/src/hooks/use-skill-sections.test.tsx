import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSkillSections } from "./use-skill-sections";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSkillSections", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      arrange: "agent",
      sections: [{ key: "unused", kind: "unused", count: 3, items: [] }],
      total: 3,
      categories: ["security"],
      suggested_categories: [],
    });
  });

  it("asks the server to arrange the whole library, not a page of it", async () => {
    const { result } = renderHook(() => useSkillSections({ arrange: "agent" }), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/skills/sections?arrange=agent&sort=name");
    expect(result.current.sections[0]?.count).toBe(3);
    expect(result.current.total).toBe(3);
    expect(result.current.categories).toEqual(["security"]);
  });

  it("keeps the listing's filters, a category repeated per shelf", async () => {
    const { result } = renderHook(
      () =>
        useSkillSections({
          arrange: "category",
          search: "refund",
          categories: ["Security", "data"],
          sort: "updated",
          groupId: "g1",
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith(
      "/skills/sections?arrange=category&sort=updated&q=refund&category=Security&category=data&group_id=g1",
    );
  });

  it("keeps a shelf with a comma apart from two shelves", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const shared = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const one = renderHook(
      () => useSkillSections({ arrange: "category", categories: ["sales,ops"] }),
      { wrapper: shared },
    );
    await waitFor(() => expect(one.result.current.isLoading).toBe(false));
    const two = renderHook(
      () => useSkillSections({ arrange: "category", categories: ["sales", "ops"] }),
      { wrapper: shared },
    );
    await waitFor(() => expect(two.result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/skills/sections?arrange=category&sort=name&category=sales&category=ops",
    );
  });

  it("asks for nothing while the page shows the plain grid", () => {
    const { result } = renderHook(() => useSkillSections({ arrange: "agent", enabled: false }), {
      wrapper,
    });

    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.sections).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.categories).toEqual([]);
  });
});
