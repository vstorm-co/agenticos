import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { useWikiGraph } from "./use-wiki-graph";
import { readWikiWorkspace } from "@/lib/wiki-workspace";

vi.mock("@/lib/wiki-workspace", () => ({ readWikiWorkspace: vi.fn() }));
afterEach(() => {
  vi.useRealTimers();
  focusManager.setFocused(undefined);
});

it("polls only the mounted view, rereads on focus and cancels when leaving", async () => {
  vi.useFakeTimers();
  const signals: AbortSignal[] = [];
  vi.mocked(readWikiWorkspace).mockImplementation(async (_, signal) => {
    signals.push(signal);
    return {
      files: [],
      pages: [],
      edges: [],
      unresolved: [],
      failed: [],
      skipped: [],
      truncated: false,
      relationshipsTruncated: false,
      metadataTruncated: false,
    };
  });
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result, unmount } = renderHook(() => useWikiGraph({ kind: "project", id: "p" }), {
    wrapper,
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(result.current.data?.pages).toEqual([]);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(readWikiWorkspace).toHaveBeenCalledTimes(2);
  await act(async () => {
    focusManager.setFocused(false);
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(readWikiWorkspace).toHaveBeenCalledTimes(2);
  await act(async () => {
    focusManager.setFocused(true);
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(readWikiWorkspace).toHaveBeenCalledTimes(3);
  vi.mocked(readWikiWorkspace).mockImplementationOnce((_source, signal) => {
    signals.push(signal);
    return new Promise((_resolve, reject) =>
      signal.addEventListener("abort", () => reject(signal.reason)),
    );
  });
  await act(async () => {
    void result.current.refetch();
    await vi.advanceTimersByTimeAsync(1);
  });
  unmount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60_000);
  });
  expect(readWikiWorkspace).toHaveBeenCalledTimes(4);
  expect(signals.at(-1)?.aborted).toBe(true);
  client.clear();
});
