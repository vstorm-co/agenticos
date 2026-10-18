import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useBrowserSignIns, useSignInToSite } from "./use-browser-sign-ins";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), delete: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PORTAL = {
  id: "s1",
  site: "portal.example.test",
  created_at: "2026-10-01T09:00:00Z",
  updated_at: null,
  last_used_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [PORTAL], total: 1 });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("the caller's kept browser sign-ins", () => {
  it("reads them on mount", async () => {
    const { result } = renderHook(() => useBrowserSignIns(), { wrapper });

    await waitFor(() => expect(result.current.signIns).toEqual([PORTAL]));
    expect(apiClient.get).toHaveBeenCalledWith("/browser-sign-ins");
  });

  it("forgets one and reads the list again, so the row leaves with the session", async () => {
    const { result } = renderHook(() => useBrowserSignIns(), { wrapper });
    await waitFor(() => expect(result.current.signIns).toHaveLength(1));
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });

    await act(async () => {
      await result.current.forget("s1");
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/browser-sign-ins/s1");
    await waitFor(() => expect(result.current.signIns).toEqual([]));
  });

  it("says so when forgetting fails, rather than leaving the row looking gone", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useBrowserSignIns(), { wrapper });
    await waitFor(() => expect(result.current.signIns).toHaveLength(1));

    await act(async () => {
      await result.current.forget("s1");
    });

    expect(toast.error).toHaveBeenCalled();
    expect(result.current.signIns).toEqual([PORTAL]);
  });
});

describe("signing in to a site from Settings", () => {
  it("is offered only once the deployment says it has a browser for it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ available: true });
    const { result } = renderHook(() => useSignInToSite(), { wrapper });

    expect(result.current.available).toBe(false);
    await waitFor(() => expect(result.current.available).toBe(true));
    expect(apiClient.get).toHaveBeenCalledWith("/browser-sign-ins/browser");
  });

  it("opens the browser on the address and answers where to watch it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ available: true });
    vi.mocked(apiClient.post).mockResolvedValue({ run_id: "sign-in-1", call_id: "sign-in" });
    const { result } = renderHook(() => useSignInToSite(), { wrapper });

    let session: unknown;
    await act(async () => {
      session = await result.current.start("https://github.com/login");
    });

    expect(apiClient.post).toHaveBeenCalledWith("/browser-sign-ins/sessions", {
      url: "https://github.com/login",
    });
    expect(session).toEqual({ run_id: "sign-in-1", call_id: "sign-in" });
  });
});
