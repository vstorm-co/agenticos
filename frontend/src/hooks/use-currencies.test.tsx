import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { currencyApi } from "@/lib/currency-api";
import { apiClient } from "@/lib/api-client";
import { useOrgStore } from "@/stores/org-store";
import { useCurrencies, useOrganizationCurrency } from "./use-currencies";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), patch: vi.fn() } }));
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const CONTEXT = {
  currency: "PLN",
  default_currency: "USD",
  inherited: false,
  rates: { USD: "1", PLN: "4" },
};
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: null });
  vi.mocked(apiClient.get).mockResolvedValue(CONTEXT);
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "org", currency: "EUR" });
});

describe("currency queries", () => {
  it("does not fetch until an organization is selected and pins the request to it", async () => {
    const { result } = renderHook(() => useCurrencies(), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
    act(() => useOrgStore.setState({ activeOrgId: "org" }));
    await waitFor(() => expect(result.current.data).toEqual(CONTEXT));
    expect(apiClient.get).toHaveBeenCalledWith("/providers/currencies", {
      headers: { "X-Organization-Id": "org" },
    });
  });
  it("reads the path organization and invalidates currency and organization data after saving", async () => {
    const { result } = renderHook(() => useOrganizationCurrency("org"), { wrapper });
    await waitFor(() => expect(result.current.context.data).toEqual(CONTEXT));
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/org/currency");
    await act(async () => {
      await result.current.save.mutateAsync("EUR");
    });
    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org", { currency: "EUR" });
    await act(async () => {
      await result.current.save.mutateAsync(null);
    });
    expect(apiClient.patch).toHaveBeenLastCalledWith("/orgs/org", { currency: null });
  });
  it("does not turn a failed read into a USD configuration", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("unavailable"));
    useOrgStore.setState({ activeOrgId: "org" });
    const { result } = renderHook(() => useCurrencies(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
  it("exposes the current currency client without relying on another tenant's selection", async () => {
    await currencyApi.current("other");
    expect(apiClient.get).toHaveBeenCalledWith("/providers/currencies", {
      headers: { "X-Organization-Id": "other" },
    });
  });
});
