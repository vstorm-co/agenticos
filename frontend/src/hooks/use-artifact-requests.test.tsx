import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  isConsentRequired,
  useArtifactRequestActions,
  useArtifactRequests,
  useRequestAccess,
  useVersionReview,
} from "./use-artifact-requests";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { ArtifactShareRequest } from "@/types/artifact";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function request(overrides: Partial<ArtifactShareRequest> = {}): ArtifactShareRequest {
  return {
    id: "r1",
    artifact_id: "a1",
    kind: "access",
    status: "pending",
    requester_user_id: "u2",
    requester_name: "Bea",
    version_id: null,
    version_number: null,
    query_fingerprint: null,
    requested_visibility: null,
    requested_subjects: [],
    note: null,
    void_reason: null,
    decided_by_user_id: null,
    decided_at: null,
    created_at: "2026-10-22T10:00:00Z",
    can_decide: true,
    ...overrides,
  };
}

function refusal(status: number, code: string) {
  return new ApiError(status, "No.", { error: { code, message: "No.", details: null } });
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("isConsentRequired", () => {
  it("is the 409 that names missing consent, and nothing else", () => {
    expect(isConsentRequired(refusal(409, "CONSENT_REQUIRED"))).toBe(true);
    expect(isConsentRequired(refusal(409, "CONCURRENT_CHANGE"))).toBe(false);
    expect(isConsentRequired(refusal(403, "CONSENT_REQUIRED"))).toBe(false);
    expect(isConsentRequired(new Error("x"))).toBe(false);
  });
});

describe("useArtifactRequests", () => {
  it("reads pending requests first, or the decided ones too on ask", async () => {
    const done = request({ id: "r0", status: "declined" });
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [done, request({ id: "r1" }), request({ id: "r2" })],
      total: 3,
    });
    const { result } = renderHook(() => useArtifactRequests("a1", true, true), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/artifacts/a1/share-requests", {
      params: { include_decided: "true" },
    });
    expect(result.current.requests.map((item) => item.id)).toEqual(["r1", "r2", "r0"]);
    expect(result.current.total).toBe(3);

    renderHook(() => useArtifactRequests("a1", false, true), { wrapper });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/artifacts/a1/share-requests", {
        params: undefined,
      }),
    );
  });

  it("reads nothing while disabled", () => {
    const { result } = renderHook(() => useArtifactRequests("a1", false, false), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.requests).toEqual([]);
  });
});

describe("useArtifactRequestActions", () => {
  it("approves and declines, reading the page and its requests again", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(request());
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useArtifactRequestActions("a1"), { wrapper });

    await act(() => result.current.approve.mutateAsync("r1"));
    expect(apiClient.post).toHaveBeenCalledWith("/artifacts/a1/share-requests/r1/approve");
    expect(toast.success).toHaveBeenCalledWith("Request approved");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["artifacts", "a1"] });

    await act(() => result.current.decline.mutateAsync("r2"));
    expect(apiClient.post).toHaveBeenCalledWith("/artifacts/a1/share-requests/r2/decline");
    expect(toast.success).toHaveBeenCalledWith("Request declined");
  });

  it("reads the requests again and says so when one was decided meanwhile", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(refusal(409, "CONCURRENT_CHANGE"));
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useArtifactRequestActions("a1"), { wrapper });

    await act(() => result.current.decline.mutateAsync("r1").catch(() => undefined));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["artifacts", "a1", "requests"] });
    expect(toast.error).toHaveBeenCalledWith("No.");
  });

  it("leaves missing consent to the caller, without a toast", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(refusal(409, "CONSENT_REQUIRED"));
    const { result } = renderHook(() => useArtifactRequestActions("a1"), { wrapper });

    await act(() => result.current.approve.mutateAsync("r1").catch(() => undefined));

    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe("useRequestAccess", () => {
  it("sends the note, or none", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "r1" });
    const { result } = renderHook(() => useRequestAccess("a1"), { wrapper });

    await act(() => result.current.mutateAsync("Need the Q3 numbers"));
    expect(apiClient.post).toHaveBeenCalledWith("/artifacts/a1/access-requests", {
      note: "Need the Q3 numbers",
    });
    await act(() => result.current.mutateAsync(null));
    expect(apiClient.post).toHaveBeenLastCalledWith("/artifacts/a1/access-requests", {
      note: null,
    });
  });

  it("says what refused it", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(refusal(429, "RATE_LIMIT_EXCEEDED"));
    const { result } = renderHook(() => useRequestAccess("a1"), { wrapper });

    await act(() => result.current.mutateAsync(null).catch(() => undefined));

    expect(toast.error).toHaveBeenCalledWith("No.");
  });
});

describe("useVersionReview", () => {
  it("reads the review of one version, only when asked", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ bindings: [] });
    renderHook(() => useVersionReview("a1", "v3", false), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();

    const { result } = renderHook(() => useVersionReview("a1", "v3", true), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.get).toHaveBeenCalledWith("/artifacts/a1/versions/v3/review");
  });
});
