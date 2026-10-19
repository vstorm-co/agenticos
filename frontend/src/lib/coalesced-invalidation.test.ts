import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { COALESCE_MS, invalidateSoon } from "./coalesced-invalidation";

afterEach(() => {
  vi.useRealTimers();
});

describe("invalidateSoon", () => {
  it("sends each key once, and none a shorter one already covers", async () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const first = invalidateSoon(client, ["conversations", "list"]);
    void invalidateSoon(client, ["conversations", "list"]);
    void invalidateSoon(client, ["conversations"]);
    void invalidateSoon(client, ["agents", "all"]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    await first;

    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual([
      ["conversations"],
      ["agents", "all"],
    ]);
  });

  it("starts a new batch once the last one has gone", async () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    void invalidateSoon(client, ["a"]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    void invalidateSoon(client, ["a"]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);

    expect(invalidate).toHaveBeenCalledTimes(2);
  });

  it("hands a failed refetch to every caller of its batch, as invalidateQueries would", async () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    vi.spyOn(client, "invalidateQueries").mockRejectedValue(new Error("offline"));

    const first = invalidateSoon(client, ["a"]).catch((error: Error) => error.message);
    const second = invalidateSoon(client, ["b"]).catch((error: Error) => error.message);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);

    await expect(first).resolves.toBe("offline");
    await expect(second).resolves.toBe("offline");
  });
});
