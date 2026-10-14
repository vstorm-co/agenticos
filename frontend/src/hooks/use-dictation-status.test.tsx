import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDictationStatus } from "./use-dictation-status";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: { get } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  get.mockReset();
});

describe("useDictationStatus", () => {
  it("answers the agent's readiness and provider", async () => {
    get.mockResolvedValue({ engine: "server", ready: true, max_seconds: 300, provider: "mistral" });

    const { result } = renderHook(() => useDictationStatus("a1"), { wrapper });

    await waitFor(() => expect(result.current.status?.provider).toBe("mistral"));
    expect(result.current.status?.ready).toBe(true);
    expect(result.current.failed).toBe(false);
    expect(get).toHaveBeenCalledWith("/agents/a1/dictation");
  });

  it("asks nothing without an agent", () => {
    const { result } = renderHook(() => useDictationStatus(null), { wrapper });

    expect(result.current).toEqual({ status: null, failed: false });
    expect(get).not.toHaveBeenCalled();
  });

  it("holds nothing of the previous agent's answer while the next one's loads", async () => {
    // A press in that moment would record in the previous agent's format and
    // call this one ready; until it answers, it is neither.
    get.mockResolvedValueOnce({
      engine: "server",
      ready: true,
      max_seconds: 300,
      provider: "mistral",
      format: "wav",
    });
    let resolveNext: (value: unknown) => void = () => {};
    get.mockReturnValueOnce(new Promise((resolve) => (resolveNext = resolve)));

    const { result, rerender } = renderHook(({ id }) => useDictationStatus(id), {
      wrapper,
      initialProps: { id: "a1" },
    });
    await waitFor(() => expect(result.current.status?.format).toBe("wav"));

    rerender({ id: "a2" });
    expect(result.current).toEqual({ status: null, failed: false });

    resolveNext({
      engine: "server",
      ready: true,
      max_seconds: 300,
      provider: "openai",
      format: "webm",
    });
    await waitFor(() => expect(result.current.status?.format).toBe("webm"));
  });

  it("says the read failed, rather than that it is still loading", async () => {
    get.mockRejectedValue(new Error("down"));

    const { result } = renderHook(() => useDictationStatus("a1"), { wrapper });

    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.status).toBeNull();
  });
});
