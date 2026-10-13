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

    await waitFor(() => expect(result.current?.provider).toBe("mistral"));
    expect(result.current?.ready).toBe(true);
    expect(get).toHaveBeenCalledWith("/agents/a1/dictation");
  });

  it("asks nothing without an agent", () => {
    const { result } = renderHook(() => useDictationStatus(null), { wrapper });

    expect(result.current).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it("keeps the previous agent's answer while the next one's loads", async () => {
    get.mockResolvedValueOnce({
      engine: "server",
      ready: true,
      max_seconds: 300,
      provider: "openai",
    });
    let resolveNext: (value: unknown) => void = () => {};
    get.mockReturnValueOnce(new Promise((resolve) => (resolveNext = resolve)));

    const { result, rerender } = renderHook(({ id }) => useDictationStatus(id), {
      wrapper,
      initialProps: { id: "a1" },
    });
    await waitFor(() => expect(result.current?.ready).toBe(true));

    rerender({ id: "a2" });
    // Not crossed out for a frame between the two answers.
    expect(result.current?.ready).toBe(true);

    resolveNext({ engine: "server", ready: false, max_seconds: 300, provider: null });
    await waitFor(() => expect(result.current?.ready).toBe(false));
  });
});
