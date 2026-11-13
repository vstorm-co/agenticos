import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useSkillVersions, versionPage } from "./use-skill-versions";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

it("finds the page of a version from its line's newest, never below the first", () => {
  expect(versionPage(120, 120)).toBe(0);
  expect(versionPage(120, 70)).toBe(1);
  expect(versionPage(120, 20)).toBe(2);
  // A newest read before a version saved since is behind the version asked for.
  expect(versionPage(1, 2)).toBe(0);
});

it("never asks the API for a page before the first", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  renderHook(() => useSkillVersions("s1", null, -1), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });

  await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
  expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions?skip=0&limit=50");
});
