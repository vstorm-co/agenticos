import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useArtifact,
  useArtifactAgents,
  useArtifacts,
  useArtifactView,
  usePublicArtifactUnlock,
} from "./use-artifacts";
import { apiClient } from "@/lib/api-client";
import type { ArtifactDetail } from "@/types/artifact";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), put: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
const unlock = vi.fn();
vi.mock("@/lib/public-artifact-api", () => ({
  unlockPublicArtifact: (...args: unknown[]) => unlock(...args),
}));
vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ apiUrl: "https://api.example" }),
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
  environment_id: null,
  environment_name: null,
  public_url: null,
  published_at: "2026-09-22T10:00:00Z",
  current_version: null,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: null,
  can_edit: true,
  following: false,
  public_link: {
    expires_at: null,
    pinned_version_id: null,
    pinned_version: null,
    password_protected: false,
    view_count: 0,
    last_viewed_at: null,
    embed_origins: [],
    embed_url: null,
  },
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

  it("narrows to one agent's pages when asked", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    renderHook(() => useArtifacts({ agentId: "ag 1" }), { wrapper });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/artifacts?agent_id=ag+1&skip=0&limit=50"),
    );
  });
});

describe("useArtifactAgents", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the publishers once it is allowed to ask", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "ag1", name: "Reporter" }] });
    const { result } = renderHook(() => useArtifactAgents(true), { wrapper });
    await waitFor(() => expect(result.current).toEqual([{ id: "ag1", name: "Reporter" }]));
    expect(apiClient.get).toHaveBeenCalledWith("/artifacts/agents");
  });

  it("asks nothing for a caller who may not see artifacts", () => {
    const { result } = renderHook(() => useArtifactAgents(false), { wrapper });
    expect(result.current).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();
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

  it("saves the link's settings and leaves a refusal to the form", async () => {
    vi.mocked(apiClient.patch).mockResolvedValueOnce(DETAIL);
    const { result } = renderHook(() => useArtifact("a1"), { wrapper });
    await waitFor(() => expect(result.current.artifact).not.toBeNull());

    await act(() => result.current.updatePublicLink.mutateAsync({ password: null }));
    expect(apiClient.patch).toHaveBeenCalledWith("/artifacts/a1/public-link", { password: null });
    expect(toastSuccess).toHaveBeenCalledWith("Public link settings saved");

    vi.mocked(apiClient.patch).mockRejectedValueOnce(new Error("bad"));
    await act(async () => {
      await result.current.updatePublicLink.mutateAsync({}).catch(() => undefined);
    });
    expect(toastError).not.toHaveBeenCalled();
  });

  it("restores a kept version and names the version it became", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ...DETAIL,
      current_version: {
        id: "v9",
        number: 9,
        media_type: "text/html",
        size_bytes: 1,
        run_id: null,
        created_at: "2026-09-30T10:00:00Z",
      },
    });
    const { result } = renderHook(() => useArtifact("a1"), { wrapper });
    await waitFor(() => expect(result.current.artifact).not.toBeNull());

    await act(() => result.current.restoreVersion.mutateAsync("v2"));
    expect(apiClient.post).toHaveBeenCalledWith("/artifacts/a1/versions/v2/restore");
    expect(toastSuccess).toHaveBeenCalledWith("Restored as version 9");

    vi.mocked(apiClient.post).mockResolvedValueOnce(DETAIL);
    await act(() => result.current.restoreVersion.mutateAsync("v1"));
    expect(toastSuccess).toHaveBeenCalledWith("Restored as version 0");

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("gone"));
    await act(async () => {
      await result.current.restoreVersion.mutateAsync("v0").catch(() => undefined);
    });
    expect(toastError).toHaveBeenCalled();
  });
});

describe("useArtifact follow", () => {
  beforeEach(() => vi.clearAllMocks());

  it("follows with a PUT, unfollows with a DELETE, and keeps the answer", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(DETAIL);
    const { result } = renderHook(() => useArtifact("a1"), { wrapper });
    await waitFor(() => expect(result.current.artifact).not.toBeNull());

    vi.mocked(apiClient.put).mockResolvedValueOnce({ ...DETAIL, following: true });
    await act(() => result.current.follow.mutateAsync(true));
    expect(apiClient.put).toHaveBeenCalledWith("/artifacts/a1/follow");
    expect(toastSuccess).toHaveBeenCalledWith(
      "You will be notified when a new version is published",
    );
    await waitFor(() => expect(result.current.artifact?.following).toBe(true));

    vi.mocked(apiClient.delete).mockResolvedValueOnce({ ...DETAIL, following: false });
    await act(() => result.current.follow.mutateAsync(false));
    expect(apiClient.delete).toHaveBeenCalledWith("/artifacts/a1/follow");
    expect(toastSuccess).toHaveBeenCalledWith("You will no longer be notified about this page");

    vi.mocked(apiClient.put).mockRejectedValueOnce(new Error("gone"));
    await act(async () => {
      await result.current.follow.mutateAsync(true).catch(() => undefined);
    });
    expect(toastError).toHaveBeenCalled();
  });
});

describe("usePublicArtifactUnlock", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends the password to this deployment's API for this link", async () => {
    unlock.mockResolvedValue({ password_required: false, title: "T" });
    const { result } = renderHook(() => usePublicArtifactUnlock("key"), { wrapper });
    await act(() => result.current.mutateAsync("hunter22"));
    expect(unlock).toHaveBeenCalledWith("https://api.example", "key", "hunter22");
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
