import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoryDangerZone, useMemoryFacts, useMemoryFile, useMemoryFiles } from "./use-memory";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useMemoryFiles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("lists one agent's files and reports the count before paging", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "f1", name: "user-preferences", origin: "operator" }],
      total: 120,
    });
    const { result } = renderHook(() => useMemoryFiles({ agentId: "a1" }), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.files[0]?.name).toBe("user-preferences");
    expect(result.current.total).toBe(120);
  });

  it("asks the server for the partition and page rather than filtering what it holds", async () => {
    const { result } = renderHook(
      () =>
        useMemoryFiles({
          agentId: "a1",
          scope: "shared",
          search: "pref",
          sort: "updated",
          skip: 50,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/files?agent_id=a1&partition=shared&sort=updated&q=pref&skip=50&limit=50",
    );
  });

  it("omits the search term from the query when there is none", async () => {
    const { result } = renderHook(() => useMemoryFiles({ agentId: "a1" }), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/files?agent_id=a1&partition=all&sort=name&skip=0&limit=50",
    );
  });

  it("posts an operator file with the agent id and reports it created", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "f1", name: "runbook" });
    const { result } = renderHook(() => useMemoryFiles({ agentId: "a1" }), { wrapper });

    await result.current.create.mutateAsync({
      name: "runbook",
      description: null,
      content: "steps",
      format: "md",
      kind: "runbook",
      end_user_scope_key: null,
    });

    expect(apiClient.post).toHaveBeenCalledWith("/memory/files", {
      agent_id: "a1",
      name: "runbook",
      description: null,
      content: "steps",
      format: "md",
      kind: "runbook",
      end_user_scope_key: null,
    });
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("deletes a file and reports it", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useMemoryFiles({ agentId: "a1" }), { wrapper });

    await result.current.remove.mutateAsync("f1");

    expect(apiClient.delete).toHaveBeenCalledWith("/memory/files/f1");
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts when a delete fails rather than swallowing it", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useMemoryFiles({ agentId: "a1" }), { wrapper });

    await expect(result.current.remove.mutateAsync("f1")).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });
});

describe("useMemoryFile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ id: "f1", name: "user-preferences" });
  });

  it("does not fetch until a file is selected", () => {
    renderHook(() => useMemoryFile("a1", null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("fetches the body of the selected file", async () => {
    const { result } = renderHook(() => useMemoryFile("a1", "f1"), { wrapper });
    await waitFor(() => expect(result.current.file?.name).toBe("user-preferences"));
    expect(apiClient.get).toHaveBeenCalledWith("/memory/files/f1");
  });

  it("saves an edit and reports it", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "f1" });
    const { result } = renderHook(() => useMemoryFile("a1", "f1"), { wrapper });

    await result.current.save.mutateAsync({
      description: "d",
      content: "c",
      format: "md",
      kind: "note",
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/memory/files/f1", {
      description: "d",
      content: "c",
      format: "md",
      kind: "note",
    });
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts when a save fails", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useMemoryFile("a1", "f1"), { wrapper });

    await expect(
      result.current.save.mutateAsync({
        description: null,
        content: "c",
        format: "md",
        kind: "note",
      }),
    ).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });

  it("promotes an agent file to trusted and reports it", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "f1", origin: "operator" });
    const { result } = renderHook(() => useMemoryFile("a1", "f1"), { wrapper });

    await result.current.promote.mutateAsync();

    expect(apiClient.post).toHaveBeenCalledWith("/memory/files/f1/promote", {});
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts when a promote fails", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useMemoryFile("a1", "f1"), { wrapper });

    await expect(result.current.promote.mutateAsync()).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });

  it("writes a saved file back over its detail cache, so a reopen is not stale", async () => {
    // The mutation writes its result over the detail key; a bare list invalidation
    // would leave a reopened (or just-promoted) file showing its pre-write state.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const scoped = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const updated = { id: "f1", name: "user-preferences", origin: "operator", content: "fresh" };
    vi.mocked(apiClient.patch).mockResolvedValue(updated);
    const { result } = renderHook(() => useMemoryFile("a1", "f1"), { wrapper: scoped });

    await result.current.save.mutateAsync({
      description: null,
      content: "fresh",
      format: "md",
      kind: "note",
    });

    expect(client.getQueryData(qk.memory.file("a1", "f1"))).toEqual(updated);
  });
});

describe("useMemoryFacts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("lists an agent's facts and reports the count", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "x1", content: "fact" }],
      total: 3,
    });
    const { result } = renderHook(() => useMemoryFacts({ agentId: "a1" }), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.total).toBe(3);
  });

  it("asks the server for the partition and page, with no sort", async () => {
    const { result } = renderHook(
      () => useMemoryFacts({ agentId: "a1", scope: "shared", search: "fy", skip: 50 }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/facts?agent_id=a1&partition=shared&q=fy&skip=50&limit=50",
    );
  });

  it("omits the filter from the query when there is none", async () => {
    const { result } = renderHook(() => useMemoryFacts({ agentId: "a1" }), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/facts?agent_id=a1&partition=all&skip=0&limit=50",
    );
  });

  it("forgets a fact and reports it", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useMemoryFacts({ agentId: "a1" }), { wrapper });

    await result.current.remove.mutateAsync("x1");

    expect(apiClient.delete).toHaveBeenCalledWith("/memory/facts/x1");
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts when forgetting a fact fails", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useMemoryFacts({ agentId: "a1" }), { wrapper });

    await expect(result.current.remove.mutateAsync("x1")).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });

  it("promotes an agent fact to trusted and reports it", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "x1", origin: "operator" });
    const { result } = renderHook(() => useMemoryFacts({ agentId: "a1" }), { wrapper });

    await result.current.promote.mutateAsync("x1");

    expect(apiClient.post).toHaveBeenCalledWith("/memory/facts/x1/promote", {});
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts when promoting a fact fails", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useMemoryFacts({ agentId: "a1" }), { wrapper });

    await expect(result.current.promote.mutateAsync("x1")).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });
});

describe("useMemoryDangerZone", () => {
  beforeEach(() => vi.clearAllMocks());

  it("clears an agent's whole memory and reports it", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useMemoryDangerZone("a1"), { wrapper });

    await result.current.clearMemory.mutateAsync();

    expect(apiClient.delete).toHaveBeenCalledWith("/memory?agent_id=a1");
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("clears an agent's facts and reports it", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useMemoryDangerZone("a1"), { wrapper });

    await result.current.clearFacts.mutateAsync();

    expect(apiClient.delete).toHaveBeenCalledWith("/memory/facts?agent_id=a1");
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts when a clear-all fails", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useMemoryDangerZone("a1"), { wrapper });

    await expect(result.current.clearMemory.mutateAsync()).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });

  it("toasts when clearing facts fails", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useMemoryDangerZone("a1"), { wrapper });

    await expect(result.current.clearFacts.mutateAsync()).rejects.toThrow();
    expect(toastError).toHaveBeenCalled();
  });
});
