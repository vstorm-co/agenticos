import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FrameInbox } from "./frame-inbox";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the frame inbox", () => {
  it("delivers a burst once per paint in its original order", () => {
    const deliver = vi.fn();
    const inbox = new FrameInbox(deliver);
    const events = Array.from({ length: 200 }, (_, n) => new MessageEvent("message", { data: n }));
    events.forEach((event) => inbox.push(event));
    expect(deliver).not.toHaveBeenCalled();
    vi.advanceTimersToNextFrame();
    expect(deliver).toHaveBeenCalledExactlyOnceWith(events);
    expect(vi.getTimerCount()).toBe(0);
    inbox.flush();
    expect(deliver).toHaveBeenCalledTimes(1);
  });

  it("still delivers in a hidden tab whose paint callback never runs", () => {
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn(() => 7),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const deliver = vi.fn();
    const inbox = new FrameInbox(deliver);
    const event = new MessageEvent("message");
    inbox.push(event);
    vi.advanceTimersByTime(50);
    expect(deliver).toHaveBeenCalledExactlyOnceWith([event]);
    expect(cancelAnimationFrame).toHaveBeenCalledWith(7);
  });

  it("bounds a large burst and schedules the remaining messages", () => {
    const deliver = vi.fn();
    const inbox = new FrameInbox(deliver);
    const event = new MessageEvent("message");
    for (let n = 0; n < 257; n++) inbox.push(event);
    expect(deliver).toHaveBeenCalledTimes(1);
    expect(deliver.mock.calls[0]![0]).toHaveLength(256);
    vi.advanceTimersToNextFrame();
    expect(deliver).toHaveBeenLastCalledWith([event]);
    expect(deliver).toHaveBeenCalledTimes(2);
  });

  it("flushes at once when a single frame exceeds the byte bound", () => {
    const deliver = vi.fn();
    const inbox = new FrameInbox(deliver);
    const big = new MessageEvent("message", { data: "x".repeat(600_000) });
    inbox.push(big);
    expect(deliver).toHaveBeenCalledExactlyOnceWith([big]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("flushes when several frames cross the byte bound, then counts again", () => {
    const deliver = vi.fn();
    const inbox = new FrameInbox(deliver);
    const chunk = () => new MessageEvent("message", { data: "x".repeat(200_000) });
    for (let n = 0; n < 2; n++) inbox.push(chunk());
    expect(deliver).not.toHaveBeenCalled();
    inbox.push(chunk());
    expect(deliver).toHaveBeenCalledTimes(1);
    expect(deliver.mock.calls[0]![0]).toHaveLength(3);
    // The count restarted: two more chunks stay queued until the timer.
    for (let n = 0; n < 2; n++) inbox.push(chunk());
    expect(deliver).toHaveBeenCalledTimes(1);
    vi.advanceTimersToNextFrame();
    expect(deliver).toHaveBeenCalledTimes(2);
  });

  it("keeps small frames waiting for the count or the timer", () => {
    const deliver = vi.fn();
    const inbox = new FrameInbox(deliver);
    for (let n = 0; n < 100; n++)
      inbox.push(new MessageEvent("message", { data: "x".repeat(1000) }));
    expect(deliver).not.toHaveBeenCalled();
    vi.advanceTimersByTime(50);
    expect(deliver).toHaveBeenCalledTimes(1);
  });

  it("cancels all deferred delivery when its owner leaves", () => {
    const deliver = vi.fn();
    const inbox = new FrameInbox(deliver);
    inbox.push(new MessageEvent("message"));
    inbox.clear();
    inbox.clear();
    vi.runAllTimers();
    inbox.flush();
    expect(deliver).not.toHaveBeenCalled();
  });

  it("does not lose messages enqueued by the consumer during delivery", () => {
    const next = new MessageEvent("message", { data: "next" });
    const deliver = vi.fn((events: readonly MessageEvent[]) => {
      if (events[0] !== next) inbox.push(next);
    });
    const inbox = new FrameInbox(deliver);
    inbox.push(new MessageEvent("message"));
    vi.advanceTimersToNextFrame();
    vi.advanceTimersToNextFrame();
    expect(deliver).toHaveBeenCalledTimes(2);
    expect(deliver).toHaveBeenLastCalledWith([next]);
  });
});
