import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useMirageBackends } from "./use-mirage-backends";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useMirageBackends", () => {
  it("reads what the terminal can mount from the deployment", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], installed: false });
    const { result } = renderHook(() => useMirageBackends(), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual({ items: [], installed: false }));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/capabilities/mirage/backends");
  });
});
