import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

import { useAssistant, useUpdateAssistant } from "./use-assistant";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), patch: vi.fn() } }));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({ toast: { error: toastError } }));

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const READY = { status: "ready", agent_id: "a1", name: "AI Architect" };

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(apiClient.get).mockReset().mockResolvedValue(READY);
  vi.mocked(apiClient.patch).mockReset();
  toastError.mockReset();
  useOrgStore.setState({ activeOrgId: "org-1" });
});

describe("useAssistant", () => {
  it("reads the organization's assistant", async () => {
    const { result } = renderHook(() => useAssistant(), { wrapper });

    await waitFor(() => expect(result.current.assistant).toEqual(READY));
    expect(apiClient.get).toHaveBeenCalledWith("/assistant");
  });

  it("asks nothing before an organization is chosen", () => {
    useOrgStore.setState({ activeOrgId: null });
    const { result } = renderHook(() => useAssistant(), { wrapper });

    expect(result.current.assistant).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useUpdateAssistant", () => {
  it("writes the change and shows the answer without reading it again", async () => {
    const renamed = { ...READY, name: "Ola" };
    vi.mocked(apiClient.patch).mockResolvedValue(renamed);
    const { result } = renderHook(() => useUpdateAssistant(), { wrapper });

    await act(() => result.current.mutateAsync({ name: "Ola" }));

    expect(apiClient.patch).toHaveBeenCalledWith("/assistant", { name: "Ola" });
    expect(client.getQueryData(qk.assistant("org-1"))).toEqual(renamed);
  });

  it("says why a change was refused", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useUpdateAssistant(), { wrapper });

    act(() => result.current.mutate({ enabled: false }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});
