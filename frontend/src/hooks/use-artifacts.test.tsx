import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useArtifact, useArtifacts, useArtifactView } from "./use-artifacts";
import { apiClient } from "@/lib/api-client";
import type { ArtifactDetail } from "@/types/artifact";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), put: vi.fn(), delete: vi.fn() },
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

const DETAIL: ArtifactDetail = {
  id: "a1",
  name: "weekly-report",
  title: "Weekly report",
  visibility: "private",
  owner_user_id: "u1",
  agent_id: "ag1",
  public_url: null,
  published_at: "2026-09-22T10:00:00Z",
  current_version: null,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: null,
  can_edit: true,
};

describe("useArtifacts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks the server for one page of what the caller may open", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [DETAIL], total: 7 });
    const { result } = renderHook(() => useArtifacts({ search: "weekly", skip: 5, limit: 5 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/artifacts?q=weekly&skip=5&limit=5");
    expect(result.current.artifacts).toHaveLength(1);
    expect(result.current.total).toBe(7);
  });

  it("answers an empty page before the first response", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useArtifacts(), { wrapper });
    expect(result.current.artifacts).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(apiClient.get).toHaveBeenCalledWith("/artifacts?skip=0&limit=50");
  });
});

describe("useArtifact", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      Promise.resolve(path.endsWith("/versions") ? { items: [], total: 0 } : DETAIL),
    );
  });

  it("reads the artifact and then its versions", async () => {
    const { result } = renderHook(() => useArtifact("a1"), { wrapper });
    await waitFor(() => expect(result.current.artifact?.title).toBe("Weekly report"));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/artifacts/a1/versions"));
    expect(result.current.versions).toEqual([]);
  });

  it("reports a refusal as an error rather than an empty artifact", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("404"));
    const { result } = renderHook(() => useArtifact("gone"), { wrapper });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.artifact).toBeNull();
  });

  it("turns the public link on and off, and says so", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ ...DETAIL, public_url: "https://x/a/k" });
    vi.mocked(apiClient.delete).mockResolvedValue(DETAIL);
    const { result } = renderHook(() => useArtifact("a1"), { wrapper });
    await waitFor(() => expect(result.current.artifact).not.toBeNull());

    // The detail is refetched after a write, so what the page ends up showing is
    // the server's answer rather than the mutation's echo of it.
    vi.mocked(apiClient.get).mockResolvedValue({ ...DETAIL, public_url: "https://x/a/k" });
    await act(() => result.current.enablePublicLink.mutateAsync());
    await waitFor(() => expect(result.current.artifact?.public_url).toBe("https://x/a/k"));
    expect(apiClient.put).toHaveBeenCalledWith("/artifacts/a1/public-link");
    expect(toastSuccess).toHaveBeenCalledWith("Public link ready");

    await act(() => result.current.disablePublicLink.mutateAsync());
    expect(apiClient.delete).toHaveBeenCalledWith("/artifacts/a1/public-link");
    expect(toastSuccess).toHaveBeenCalledWith("Public link turned off");
  });

  it("deletes it and toasts, or toasts the refusal", async () => {
    vi.mocked(apiClient.delete).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useArtifact("a1"), { wrapper });
    await waitFor(() => expect(result.current.artifact).not.toBeNull());

    await act(() => result.current.remove.mutateAsync());
    expect(apiClient.delete).toHaveBeenCalledWith("/artifacts/a1");
    expect(toastSuccess).toHaveBeenCalledWith("Artifact deleted");

    vi.mocked(apiClient.put).mockRejectedValueOnce(new Error("nope"));
    await act(async () => {
      await result.current.enablePublicLink.mutateAsync().catch(() => undefined);
    });
    expect(toastError).toHaveBeenCalled();
  });
});

describe("useArtifactView", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks for the current version when none is named", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      url: "https://api/x",
      expires_at: "",
      version: {},
    });
    const { result } = renderHook(() => useArtifactView("a1", null, true), { wrapper });
    await waitFor(() => expect(result.current.data?.url).toBe("https://api/x"));
    expect(apiClient.get).toHaveBeenCalledWith("/artifacts/a1/view");
  });

  it("names the version a link pinned", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ url: "u", expires_at: "", version: {} });
    renderHook(() => useArtifactView("a1", "v 2", true), { wrapper });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/artifacts/a1/view?version_id=v%202"),
    );
  });

  it("asks nothing until it is enabled", () => {
    renderHook(() => useArtifactView("a1", null, false), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
