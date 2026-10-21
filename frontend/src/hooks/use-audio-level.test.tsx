import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LEVEL_EVERY_MS, useAudioLevel } from "./use-audio-level";

const disconnect = vi.fn();
let context: unknown = null;
let amplitude = 64;

vi.mock("voice-glow", () => ({ getAudioContext: () => context }));

function fakeContext() {
  return {
    createMediaStreamSource: () => ({ connect: vi.fn(), disconnect }),
    createAnalyser: () => ({
      fftSize: 0,
      getByteTimeDomainData(samples: Uint8Array) {
        for (let i = 0; i < samples.length; i++) {
          samples[i] = 128 + Math.round(amplitude * Math.sin((i / samples.length) * Math.PI * 8));
        }
      },
    }),
  };
}

function stream(tracks: number): MediaStream {
  return {
    getAudioTracks: () => Array.from({ length: tracks }, () => ({})),
  } as unknown as MediaStream;
}

beforeEach(() => {
  vi.useFakeTimers();
  disconnect.mockReset();
  amplitude = 64;
  context = fakeContext();
});

afterEach(() => vi.useRealTimers());

describe("useAudioLevel", () => {
  it("follows how loud the stream is, and lets go of it when done", () => {
    const mic = stream(1);
    const { result, unmount } = renderHook(() => useAudioLevel(mic));
    act(() => vi.advanceTimersByTime(LEVEL_EVERY_MS * 5));
    expect(result.current).toBeGreaterThan(0.2);
    unmount();
    expect(disconnect).toHaveBeenCalled();
  });

  it("falls back towards silence slower than it rises", () => {
    const mic = stream(1);
    const { result } = renderHook(() => useAudioLevel(mic));
    act(() => vi.advanceTimersByTime(LEVEL_EVERY_MS * 10));
    const loud = result.current;
    amplitude = 0;
    act(() => vi.advanceTimersByTime(LEVEL_EVERY_MS));
    // One release step keeps most of the level; one attack step took a third.
    expect(result.current).toBeLessThan(loud);
    expect(result.current).toBeGreaterThan(loud * 0.8);
  });

  it("is still with no stream, no audio track or no audio context", () => {
    expect(renderHook(() => useAudioLevel(null)).result.current).toBe(0);
    expect(renderHook(() => useAudioLevel(stream(0))).result.current).toBe(0);
    context = null;
    const mic = stream(1);
    const { result } = renderHook(() => useAudioLevel(mic));
    act(() => vi.advanceTimersByTime(LEVEL_EVERY_MS * 5));
    expect(result.current).toBe(0);
  });
});
