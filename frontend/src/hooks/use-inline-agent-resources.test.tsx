import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useInlineAgentResources } from "./use-inline-agent-resources";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => vi.clearAllMocks());

it("loads resources past the first 100 for both local galleries", async () => {
  vi.mocked(apiClient.get).mockImplementation(async (url) => {
    const parsed = new URL(url, "https://example.test");
    const skip = Number(parsed.searchParams.get("skip"));
    return {
      items: Array.from({ length: skip === 0 ? 100 : 1 }, (_, i) => ({
        id: `${parsed.pathname}-${skip + i}`,
      })),
      total: 101,
    };
  });
  const { result } = renderHook(() => useInlineAgentResources(), { wrapper });
  expect(result.current.isLoading).toBe(true);
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  expect(result.current.skills.at(-1)?.id).toBe("/skills-100");
  expect(result.current.contextFiles.at(-1)?.id).toBe("/context-100");
  expect(result.current.skillTotal).toBe(101);
  expect(result.current.contextTotal).toBe(101);
  expect(apiClient.get).toHaveBeenCalledTimes(4);
});

it("accepts empty catalogs", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  const { result } = renderHook(() => useInlineAgentResources(), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  expect(result.current.skills).toEqual([]);
  expect(result.current.contextFiles).toEqual([]);
  expect(result.current.error).toBeNull();
});

it.each(["/skills", "/context"])(
  "does not expose a failed partial %s catalog as complete, and retries",
  async (failedPath) => {
    let broken = true;
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      const parsed = new URL(url, "https://example.test");
      if (parsed.pathname === failedPath && parsed.searchParams.get("skip") === "1" && broken)
        throw new Error("offline");
      const skip = Number(parsed.searchParams.get("skip"));
      return { items: [{ id: `${parsed.pathname}-${skip}` }], total: 2 };
    });
    const { result } = renderHook(() => useInlineAgentResources(), { wrapper });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(failedPath === "/skills" ? result.current.skills : result.current.contextFiles).toEqual(
      [],
    );
    broken = false;
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.skillTotal).toBe(2);
    expect(result.current.contextTotal).toBe(2);
  },
);

it("refuses a truncated catalog instead of inventing missing resources", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 2 });
  const { result } = renderHook(() => useInlineAgentResources(), { wrapper });
  await waitFor(() => expect(result.current.error).not.toBeNull());
  expect(result.current.skills).toEqual([]);
});
