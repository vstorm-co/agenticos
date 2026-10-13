import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMessageRating } from "./use-message-rating";
import * as api from "@/lib/message-rating-api";
import { RatingValue } from "@/types/chat";

vi.mock("@/lib/message-rating-api", () => ({
  rateMessage: vi.fn(),
  removeRating: vi.fn(),
}));

function wrapperFor(client: QueryClient) {
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestWrapper";
  return Wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.rateMessage).mockResolvedValue({});
  vi.mocked(api.removeRating).mockResolvedValue(undefined);
});

describe("useMessageRating", () => {
  it("rates through the client and invalidates the rating summaries", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useMessageRating("c-1", "m-1"), {
      wrapper: wrapperFor(client),
    });

    await result.current.rateMessage({ rating: RatingValue.LIKE, comment: null });

    expect(api.rateMessage).toHaveBeenCalledWith("c-1", "m-1", {
      rating: RatingValue.LIKE,
      comment: null,
    });
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["ratings"] });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin", "ratings"] });
    });
  });

  it("removes through the client and invalidates the summaries", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useMessageRating("c-1", "m-1"), {
      wrapper: wrapperFor(client),
    });

    await result.current.removeRating();

    expect(api.removeRating).toHaveBeenCalledWith("c-1", "m-1");
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["ratings"] }));
  });
});
