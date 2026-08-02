/**
 * The poll that replaced the `/rag` status stream.
 *
 * Two properties are worth holding onto, and neither is visible from reading the
 * hook: that it stops (a page with a settled list must make no requests at all,
 * or this is worse than the stream it replaced), and that an inline callback
 * does not stall it - the mistake the ref in the hook exists to prevent, and one
 * that looks perfectly correct on the page calling it.
 */

import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePollWhileIngesting } from "./use-poll-while-ingesting";

const DONE = [{ id: "a", status: "done" }];

/** A fresh array each time, because that is what a refetch hands the page: the
 * hook reschedules on the list's identity, so reusing one array would test a
 * component that never re-renders. */
const ingesting = () => [{ id: "a", status: "processing" }];

describe("usePollWhileIngesting", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not poll a list with nothing left to ingest", () => {
    const refresh = vi.fn();

    renderHook(() => usePollWhileIngesting(DONE, refresh));
    vi.advanceTimersByTime(60_000);

    expect(refresh).not.toHaveBeenCalled();
  });

  it("refreshes while a document is still processing", () => {
    const refresh = vi.fn();

    renderHook(() => usePollWhileIngesting(ingesting(), refresh));
    vi.advanceTimersByTime(2_000);

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("keeps polling when the caller passes a fresh callback each render", () => {
    // `usePollWhileIngesting(docs, () => fetchDocs(selected))` is how a page
    // naturally writes this. With the callback in the effect's dependencies,
    // every re-render would clear the pending timer and start a new one, and the
    // poll would never fire on a page that re-renders at all.
    // The list is held constant so the callback is the only thing that changes:
    // if that were enough to reschedule, the timer would restart at 1.5s and the
    // refresh at 2s would never happen.
    const unchanged = ingesting();
    let calls = 0;
    const { rerender } = renderHook(() =>
      usePollWhileIngesting(unchanged, () => {
        calls += 1;
      }),
    );

    vi.advanceTimersByTime(1_500);
    rerender();
    vi.advanceTimersByTime(1_000);

    expect(calls).toBe(1);
  });

  it("stops once the last document settles", () => {
    const refresh = vi.fn();
    const { rerender } = renderHook(({ documents }) => usePollWhileIngesting(documents, refresh), {
      initialProps: { documents: ingesting() },
    });

    vi.advanceTimersByTime(2_000);
    rerender({ documents: DONE });
    vi.advanceTimersByTime(60_000);

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("keeps polling when the caller hands back the very same array", () => {
    // What a caller holding the list in React Query does: structural sharing
    // returns the previous `data` reference when a poll finds nothing changed.
    // The schedule used to be armed by that reference moving, so a document
    // stuck at `processing` was polled exactly once and then never again.
    const refresh = vi.fn();
    const documents = ingesting();
    const { rerender } = renderHook(() => usePollWhileIngesting(documents, refresh));

    vi.advanceTimersByTime(2_000);
    expect(refresh).toHaveBeenCalledTimes(1);

    rerender();
    vi.advanceTimersByTime(3_000);

    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("backs off while nothing changes, and speeds up again when something does", () => {
    // A large PDF can take minutes; a fixed 2s interval is hundreds of requests
    // for one document. The reset matters just as much: the tick after a status
    // flips has to be fast, or a finished ingest sits stale on screen for 30s.
    const refresh = vi.fn();
    const { rerender } = renderHook(({ documents }) => usePollWhileIngesting(documents, refresh), {
      initialProps: { documents: ingesting() },
    });

    vi.advanceTimersByTime(2_000);
    rerender({ documents: ingesting() });
    vi.advanceTimersByTime(2_999);
    expect(refresh).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(refresh).toHaveBeenCalledTimes(2);

    rerender({
      documents: [
        { id: "a", status: "processing" },
        { id: "b", status: "pending" },
      ],
    });
    vi.advanceTimersByTime(2_000);

    expect(refresh).toHaveBeenCalledTimes(3);
  });
});
