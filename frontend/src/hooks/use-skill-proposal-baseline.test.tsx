import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useSkillProposalBaseline, useSkillProposalFile } from "./use-skill-proposal-baseline";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => vi.mocked(apiClient.get).mockReset());

it("compares against the current main version", async () => {
  vi.mocked(apiClient.get)
    .mockResolvedValueOnce({ latest_version_id: "v2", version: 2 })
    .mockResolvedValueOnce({ id: "v2", content: "main" });
  const { result } = renderHook(() => useSkillProposalBaseline("s1", null), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.content).toBe("main");
  expect(apiClient.get).toHaveBeenLastCalledWith("/skills/s1/versions/v2");
});

it.each([null, { id: "fork-v3" }])(
  "uses a fork's own version, or its base before its first edit",
  async (latest) => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [{ id: "f1", latest, base: { id: "base-v2" } }] })
      .mockResolvedValueOnce({ id: latest?.id ?? "base-v2", content: "fork" });
    const { result } = renderHook(() => useSkillProposalBaseline("s1", "f1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.get).toHaveBeenLastCalledWith(
      `/skills/s1/versions/${latest?.id ?? "base-v2"}`,
    );
  },
);

it("does not substitute main for an unavailable fork", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [] });
  const { result } = renderHook(() => useSkillProposalBaseline("s1", "missing"), { wrapper });
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(apiClient.get).toHaveBeenCalledTimes(1);
});

it("does not load a baseline for a new skill", () => {
  renderHook(() => useSkillProposalBaseline(null, null), { wrapper });
  expect(apiClient.get).not.toHaveBeenCalled();
});

it("fetches only the selected immutable reference file with encoded path segments", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ content: "old file" });
  const { result } = renderHook(() => useSkillProposalFile("s1", "v2", "references/a #1.md"), {
    wrapper,
  });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.content).toBe("old file");
  expect(apiClient.get).toHaveBeenCalledWith(
    "/skills/s1/versions/v2/resources/references/a%20%231.md",
  );
});

it("rejects a manual baseline refresh before a skill exists", async () => {
  const { result } = renderHook(() => useSkillProposalBaseline(null, null), { wrapper });
  await act(async () => {
    const refreshed = await result.current.refetch();
    expect(refreshed.isError).toBe(true);
    expect(refreshed.error).toBeInstanceOf(Error);
  });
  expect(apiClient.get).not.toHaveBeenCalled();
});

it("refuses to fetch a version when main has not been published", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ latest_version_id: null, version: 0 });
  const { result } = renderHook(() => useSkillProposalBaseline("s1", null), { wrapper });
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(apiClient.get).toHaveBeenCalledTimes(1);
});
