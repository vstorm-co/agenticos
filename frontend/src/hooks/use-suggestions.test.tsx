import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listSuggestions: vi.fn(),
  acceptSuggestion: vi.fn(),
  dismissSuggestion: vi.fn(),
  listSuggestionHistory: vi.fn(),
  listPersonalStarters: vi.fn(),
  restoreSuggestion: vi.fn(),
}));
vi.mock("@/lib/suggestions-api", () => api);

import { usePersonalStarterQuery, useSuggestionHistory, useSuggestions } from "./use-suggestions";

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

describe("useSuggestionHistory", () => {
  it("reads every proposal, and brings a declined one back to the open ones", async () => {
    api.listSuggestionHistory.mockResolvedValue([{ id: "s1", status: "dismissed" }]);
    api.restoreSuggestion.mockResolvedValue({ id: "s1", status: "open" });
    const { result } = renderHook(() => useSuggestionHistory(), { wrapper });

    await waitFor(() =>
      expect(result.current.history).toEqual([{ id: "s1", status: "dismissed" }]),
    );
    await result.current.restore("s1");

    expect(api.restoreSuggestion).toHaveBeenCalledWith("s1");
    // The history sits under the open list's key, so both are read again.
    await waitFor(() => expect(api.listSuggestionHistory).toHaveBeenCalledTimes(2));
  });
});

describe("usePersonalStarterQuery", () => {
  it("reuses fresh starters across mounts and does not fetch for another agent", async () => {
    api.listPersonalStarters.mockClear();
    api.listPersonalStarters.mockResolvedValue(["Plan my week"]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const shared = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const disabled = renderHook(() => usePersonalStarterQuery(false), { wrapper: shared });
    expect(api.listPersonalStarters).not.toHaveBeenCalled();
    disabled.unmount();
    const first = renderHook(() => usePersonalStarterQuery(), { wrapper: shared });
    await waitFor(() => expect(first.result.current.data).toEqual(["Plan my week"]));
    first.unmount();
    const second = renderHook(() => usePersonalStarterQuery(), { wrapper: shared });
    expect(second.result.current.data).toEqual(["Plan my week"]);
    expect(api.listPersonalStarters).toHaveBeenCalledTimes(1);
    second.unmount();
    client.clear();
  });

  it("offers none until they are read, then the ones written for the person", async () => {
    api.listPersonalStarters.mockResolvedValue(["Plan my week"]);

    const { result } = renderHook(() => usePersonalStarterQuery(), { wrapper });

    expect(result.current.data).toBeUndefined();
    await waitFor(() => expect(result.current.data).toEqual(["Plan my week"]));
  });
});
