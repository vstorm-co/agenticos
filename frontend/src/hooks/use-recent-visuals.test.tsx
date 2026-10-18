import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const { listRecentVisuals } = vi.hoisted(() => ({ listRecentVisuals: vi.fn() }));
vi.mock("@/lib/visuals-api", () => ({ listRecentVisuals }));

import { useRecentVisuals } from "./use-recent-visuals";

describe("useRecentVisuals", () => {
  it("reads the caller's latest drawings", async () => {
    listRecentVisuals.mockResolvedValue({ items: [{ id: "v1" }] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useRecentVisuals(6), { wrapper });
    expect(result.current.visuals).toEqual([]);
    await waitFor(() => expect(result.current.visuals).toEqual([{ id: "v1" }]));
    expect(listRecentVisuals).toHaveBeenCalledWith(6);
  });
});
