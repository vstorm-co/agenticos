import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import * as api from "@/lib/workflows/exposures-api";

import { useWebhookTest } from "./use-webhook-test";

vi.mock("@/lib/workflows/exposures-api", () => ({
  listenForWebhookTest: vi.fn(),
  getWebhookTest: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const LISTENING = {
  test_token: "tok",
  url: "https://x/api/v1/workflow-webhook-tests/tok",
  expires_at: "",
};

beforeEach(() => vi.clearAllMocks());

describe("useWebhookTest", () => {
  it("opens a test URL, asks until its call has come, and forgets it on stop", async () => {
    vi.mocked(api.listenForWebhookTest).mockResolvedValue(LISTENING);
    vi.mocked(api.getWebhookTest)
      .mockResolvedValueOnce({ state: "listening", delivery: null })
      .mockResolvedValue({ state: "caught", delivery: { body: {}, delivery_id: "d" } });
    const { result } = renderHook(() => useWebhookTest("wf"), { wrapper });
    expect(result.current.capture).toBeNull();

    await act(() => result.current.listen.mutateAsync());
    expect(result.current.listening).toEqual(LISTENING);
    await waitFor(() => expect(result.current.capture?.state).toBe("listening"));
    await waitFor(() => expect(result.current.capture?.state).toBe("caught"), { timeout: 3000 });
    expect(api.getWebhookTest).toHaveBeenCalledWith("wf", "tok");

    act(() => result.current.stop());
    expect(result.current.listening).toBeNull();
    expect(result.current.capture).toBeNull();
  });

  it("says why a test URL could not be opened", async () => {
    vi.mocked(api.listenForWebhookTest).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useWebhookTest("wf"), { wrapper });
    await act(async () => {
      await result.current.listen.mutateAsync().catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalled();
  });
});
