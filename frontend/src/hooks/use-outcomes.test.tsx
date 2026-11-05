import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { listConversationOutcomes, settleOutcome } from "@/lib/outcomes-api";
import { useConversationOutcomes, useSettleOutcome } from "./use-outcomes";

vi.mock("@/lib/outcomes-api", () => ({
  listConversationOutcomes: vi.fn(),
  settleOutcome: vi.fn(),
}));

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { Wrapper, invalidate };
}

const outcome = (status: "open" | "acknowledged") => ({
  id: status,
  kind: "finding",
  summary: "Found it",
  context_url: null,
  status,
  source_conversation_id: "c-1",
  created_at: "2026-11-01T10:00:00Z",
  settled_at: null,
  settled_via: null,
});

describe("useConversationOutcomes", () => {
  it("keeps only what is still open, and reads nothing without a chat", async () => {
    vi.mocked(listConversationOutcomes).mockResolvedValue([
      outcome("open"),
      outcome("acknowledged"),
    ]);
    const { Wrapper } = wrapper();

    const { result } = renderHook(() => useConversationOutcomes("c-1"), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.outcomes).toHaveLength(1));
    expect(result.current.outcomes[0]?.status).toBe("open");

    vi.mocked(listConversationOutcomes).mockClear();
    const none = renderHook(() => useConversationOutcomes(null), { wrapper: Wrapper });
    expect(none.result.current.outcomes).toEqual([]);
    expect(listConversationOutcomes).not.toHaveBeenCalled();
  });
});

describe("useSettleOutcome", () => {
  it("settles through where it was done and refreshes everything that shows it", async () => {
    vi.mocked(settleOutcome).mockResolvedValue(outcome("open"));
    const { Wrapper, invalidate } = wrapper();
    const { result } = renderHook(() => useSettleOutcome("chat"), { wrapper: Wrapper });

    await act(() => result.current.settle({ id: "o-1", action: "mute" }));

    expect(settleOutcome).toHaveBeenCalledWith("o-1", "mute", "chat");
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(6));
    expect(invalidate.mock.calls.map((call) => call[0]?.queryKey)).toEqual([
      ["outcomes"],
      ["durable-tasks"],
      ["tables"],
      ["notifications"],
      ["suggestions"],
      ["watches"],
    ]);
  });
});

it("exposes failed outcome reads and lets the person retry", async () => {
  const error = new Error("offline");
  vi.mocked(listConversationOutcomes).mockRejectedValueOnce(error).mockResolvedValueOnce([]);
  const { Wrapper } = wrapper();
  const { result } = renderHook(() => useConversationOutcomes("retry-chat"), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.error).toBe(error));
  await act(() => result.current.retry());
  await waitFor(() => expect(result.current.error).toBeNull());
  expect(result.current.outcomes).toEqual([]);
});
