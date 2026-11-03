import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCopyToClipboard } from "./use-copy-to-clipboard";

describe("useCopyToClipboard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("says copied until the reset, restarting it on a second copy", async () => {
    const { result } = renderHook(() => useCopyToClipboard(1000));

    await act(() => result.current.copy("one"));
    act(() => vi.advanceTimersByTime(600));
    await act(() => result.current.copy("two"));
    act(() => vi.advanceTimersByTime(600));
    expect(result.current.copied).toBe(true);

    act(() => vi.advanceTimersByTime(400));
    expect(result.current.copied).toBe(false);
  });

  it("leaves no reset behind once unmounted", async () => {
    const { result, unmount } = renderHook(() => useCopyToClipboard());

    await act(() => result.current.copy("text"));
    unmount();

    expect(vi.getTimerCount()).toBe(0);
  });

  it("schedules nothing when unmounted while the write is still pending", async () => {
    let finish: () => void = () => {};
    vi.mocked(navigator.clipboard.writeText).mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const { result, unmount } = renderHook(() => useCopyToClipboard());

    const copying = result.current.copy("text");
    unmount();
    finish();

    await expect(copying).resolves.toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
