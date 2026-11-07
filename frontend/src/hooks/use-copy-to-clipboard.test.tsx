import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useCopyToClipboard } from "./use-copy-to-clipboard";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("cancels feedback when the copied card unmounts", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  const { result, unmount } = renderHook(() => useCopyToClipboard());
  await act(async () => {
    expect(await result.current.copy("Draft")).toBe(true);
  });
  expect(result.current.copied).toBe(true);
  expect(vi.getTimerCount()).toBe(1);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("does not schedule feedback when an asynchronous copy finishes after unmount", async () => {
  vi.useFakeTimers();
  const { promise: written, resolve: finish } = Promise.withResolvers<void>();
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn(() => written) } });
  const { result, unmount } = renderHook(() => useCopyToClipboard());
  const copied = result.current.copy("Draft");
  unmount();
  finish();
  expect(await copied).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it("restarts feedback for a new copy and clears it once", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  const { result } = renderHook(() => useCopyToClipboard(100));
  await act(async () => {
    await result.current.copy("One");
  });
  act(() => vi.advanceTimersByTime(50));
  await act(async () => {
    await result.current.copy("Two");
  });
  act(() => vi.advanceTimersByTime(50));
  expect(result.current.copied).toBe(true);
  act(() => vi.advanceTimersByTime(50));
  expect(result.current.copied).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
});
