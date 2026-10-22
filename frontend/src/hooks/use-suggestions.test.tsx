import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listSuggestions: vi.fn(),
  acceptSuggestion: vi.fn(),
  dismissSuggestion: vi.fn(),
}));
vi.mock("@/lib/suggestions-api", () => api);

import { useSuggestions } from "./use-suggestions";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSuggestions", () => {
  it("reads the open ones and reads them again after either answer", async () => {
    api.listSuggestions.mockResolvedValue([{ id: "s1" }]);
    api.acceptSuggestion.mockResolvedValue({ id: "s1" });
    api.dismissSuggestion.mockResolvedValue({ id: "s1" });
    const { result } = renderHook(() => useSuggestions(), { wrapper });

    await waitFor(() => expect(result.current.suggestions).toEqual([{ id: "s1" }]));
    await result.current.accept("s1");
    await result.current.dismiss("s1");

    await waitFor(() => expect(api.listSuggestions).toHaveBeenCalledTimes(3));
    expect(api.acceptSuggestion).toHaveBeenCalledWith("s1");
    expect(api.dismissSuggestion).toHaveBeenCalledWith("s1");
  });
});
