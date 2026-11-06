import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { phoneApi } from "@/lib/phone-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import { phoneContact, phoneSettings, phoneCall } from "@/test-utils/phone";
import { usePhoneCall, usePhoneCalls, usePhoneSettings } from "./use-phone";

vi.mock("@/lib/phone-api", async (original) => ({
  ...(await original<typeof import("@/lib/phone-api")>()),
  phoneApi: {
    settings: vi.fn(),
    saveContact: vi.fn(),
    configure: vi.fn(),
    call: vi.fn(),
    calls: vi.fn(),
    receipt: vi.fn(),
  },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org" });
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  vi.mocked(phoneApi.settings).mockResolvedValue(phoneSettings);
  vi.mocked(phoneApi.calls).mockResolvedValue([]);
  vi.mocked(phoneApi.receipt).mockResolvedValue(phoneCall);
});
it("refreshes private settings after consent and call mutations", async () => {
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => usePhoneSettings(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  await act(async () => {
    await result.current.saveContact.mutateAsync(phoneContact);
  });
  await act(async () => {
    await result.current.call.mutateAsync({
      request_key: "request",
      endpoint_id: "endpoint",
      mode: "report",
      report: "Ready",
    });
  });
  const data = {
    enabled: true,
    inbound_embed_id: null,
    max_call_seconds: 60,
    calls_per_hour: 2,
    calls_per_day: 3,
    max_concurrent: 1,
    daily_budget_usd: 5,
    price_per_minute_usd: 0.1,
    transfer_contact_ids: [],
  };
  await act(async () => {
    await result.current.configure.mutateAsync({ botId: "bot", data });
  });
  expect(phoneApi.configure).toHaveBeenCalledWith("bot", data);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.phone.all("org") });
  vi.mocked(phoneApi.call).mockRejectedValueOnce(new Error("Call unavailable"));
  await act(async () => {
    await expect(
      result.current.call.mutateAsync({
        request_key: "request",
        endpoint_id: "endpoint",
        mode: "conversation",
      }),
    ).rejects.toThrow();
  });
  expect(toast.error).toHaveBeenCalled();
});
it("polls active receipts but stops polling ended calls", async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(phoneApi.calls).mockResolvedValue([phoneCall]);
    renderHook(() => usePhoneCalls(), { wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(phoneApi.calls).toHaveBeenCalledTimes(1);
    vi.mocked(phoneApi.calls).mockResolvedValue([{ ...phoneCall, status: "completed" }]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(phoneApi.calls).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(phoneApi.calls).toHaveBeenCalledTimes(2);
  } finally {
    vi.useRealTimers();
  }
});
it("polls a private receipt until it ends and scopes the next read to the new organization", async () => {
  useOrgStore.setState({ activeOrgId: null });
  vi.useFakeTimers();
  try {
    renderHook(() => usePhoneCall("call"), { wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(phoneApi.receipt).toHaveBeenCalledWith("call");
    expect(client.getQueryData(qk.phone.call("current", "call"))).toEqual(phoneCall);
    vi.mocked(phoneApi.receipt).mockResolvedValue({ ...phoneCall, status: "failed" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(phoneApi.receipt).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(phoneApi.receipt).toHaveBeenCalledTimes(2);
    act(() => useOrgStore.setState({ activeOrgId: "next" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(client.getQueryData(qk.phone.call("next", "call"))).toEqual(
      expect.objectContaining({ status: "failed" }),
    );
  } finally {
    vi.useRealTimers();
  }
});
