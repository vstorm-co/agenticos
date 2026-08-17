import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useContextFile, useContextFiles } from "./use-context";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
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
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useContextFiles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("lists the organization's context files", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "c1", name: "glossary", mode: "inject" }],
      total: 1,
    });
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.files[0]?.name).toBe("glossary");
  });

  it("asks the database for the slice rather than filtering what it holds", async () => {
    const { result } = renderHook(
      () => useContextFiles({ search: "gloss", sort: "updated", skip: 50, limit: 50 }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/context?q=gloss&sort=updated&skip=50&limit=50");
  });

  it("reports the count before paging", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 120 });
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.total).toBe(120);
  });

  it("creates a context file", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ name: "glossary" });
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.create.mutateAsync({
      name: "glossary",
      description: "terms",
      content: "SLA: ...",
      format: "md",
      mode: "inject",
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/context",
      expect.objectContaining({ name: "glossary", mode: "inject" }),
    );
    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/glossary/);
  });

  it("says an edit reaches every agent at once", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ name: "glossary" });
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.update.mutateAsync({ id: "c1", mode: "link" });

    expect(apiClient.patch).toHaveBeenCalledWith("/context/c1", { mode: "link" });
    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/every agent/i);
  });

  it("deletes a context file", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.remove.mutateAsync("c1");
    expect(apiClient.delete).toHaveBeenCalledWith("/context/c1");
  });

  it("omits the search param when there is no query", async () => {
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/context?sort=name&skip=0&limit=50");
  });
});

describe("useContextFiles failures", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("surfaces a failed read for the page to render", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("bad gateway"));
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error?.message).toBe("bad gateway");
  });

  it("leaves a failed creation to the dialog, with no toast", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("name taken"));
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await expect(
      result.current.create.mutateAsync({
        name: "glossary",
        description: null,
        content: "",
        format: "md",
        mode: "inject",
      }),
    ).rejects.toThrow();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("reports a failed edit", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("conflict"));
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await expect(result.current.update.mutateAsync({ id: "c1" })).rejects.toThrow();
    expect(toastError).toHaveBeenCalledWith("conflict");
  });

  it("reports a failed delete", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("in use"));
    const { result } = renderHook(() => useContextFiles(), { wrapper });
    await expect(result.current.remove.mutateAsync("c1")).rejects.toThrow();
    expect(toastError).toHaveBeenCalledWith("in use");
  });
});

const BODY = {
  id: "c1",
  name: "glossary",
  description: "terms",
  content: "SLA: service level agreement.",
  format: "md",
  mode: "inject" as const,
  enabled: true,
  visibility: "organization",
  owner_user_id: null,
};

describe("useContextFile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(BODY);
  });

  it("loads the body the list left out", async () => {
    const { result } = renderHook(() => useContextFile("c1"), { wrapper });
    await waitFor(() => expect(result.current.file).toEqual(BODY));
    expect(apiClient.get).toHaveBeenCalledWith("/context/c1");
  });

  it("asks for nothing until a file is opened", () => {
    renderHook(() => useContextFile(null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("sends the whole editable set so an unticked toggle is not lost", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(BODY);
    const { result } = renderHook(() => useContextFile("c1"), { wrapper });
    await waitFor(() => expect(result.current.file).toEqual(BODY));

    await result.current.save.mutateAsync({
      description: null,
      content: "new",
      format: "txt",
      mode: "link",
      enabled: false,
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/context/c1", {
      description: null,
      content: "new",
      format: "txt",
      mode: "link",
      enabled: false,
    });
    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/every agent/i);
  });

  it("reports a failed save", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("stale"));
    const { result } = renderHook(() => useContextFile("c1"), { wrapper });
    await waitFor(() => expect(result.current.file).toEqual(BODY));
    await expect(
      result.current.save.mutateAsync({
        description: null,
        content: "x",
        format: "md",
        mode: "inject",
        enabled: true,
      }),
    ).rejects.toThrow();
    expect(toastError).toHaveBeenCalledWith("stale");
  });
});
