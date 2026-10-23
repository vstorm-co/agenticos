import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import { usePublicOpenApi } from "./use-public-openapi";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("usePublicOpenApi", () => {
  it("reads the public OpenAPI document, and nothing until it arrives", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ info: { title: "t", version: "1" }, paths: {} });
    const { result } = renderHook(() => usePublicOpenApi(), { wrapper });

    expect(result.current.document).toBeNull();
    await waitFor(() => expect(result.current.document?.info.version).toBe("1"));
    expect(apiClient.get).toHaveBeenCalledWith("/public/openapi.json");
  });
});
