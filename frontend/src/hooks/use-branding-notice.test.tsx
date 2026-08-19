import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useBrandingNotice } from "./use-branding-notice";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("the announcement banner's read", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ message: "Window at 22:00", level: "warning" });
  });

  it("asks the endpoint behind the session", async () => {
    const { result } = renderHook(() => useBrandingNotice(true), { wrapper });

    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(apiClient.get).toHaveBeenCalledWith("/branding/notice");
    expect(result.current.data?.message).toBe("Window at 22:00");
  });

  it("does not ask at all when nobody is signed in", async () => {
    // The endpoint refuses that, so a sign-in page asking for an operator's
    // upgrade notes would be a 401 on every cold load.
    renderHook(() => useBrandingNotice(false), { wrapper });

    await waitFor(() => expect(apiClient.get).not.toHaveBeenCalled());
  });
});
