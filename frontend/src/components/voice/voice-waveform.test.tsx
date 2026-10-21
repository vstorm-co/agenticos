import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceWaveform } from "./voice-waveform";

/** A 2D context that records what was painted. */
function fakeContext() {
  const fills: { style: unknown; alpha: number }[] = [];
  const context = {
    globalAlpha: 1,
    fillStyle: "" as unknown,
    setTransform: vi.fn(),
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    roundRect: vi.fn(),
    fill: vi.fn(() => fills.push({ style: context.fillStyle, alpha: context.globalAlpha })),
  };
  return { context, fills };
}

let frames: FrameRequestCallback[] = [];
const size = { width: 120, height: 44 };

beforeEach(() => {
  frames = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  vi.spyOn(HTMLCanvasElement.prototype, "clientWidth", "get").mockImplementation(() => size.width);
  vi.spyOn(HTMLCanvasElement.prototype, "clientHeight", "get").mockImplementation(
    () => size.height,
  );
  document.documentElement.style.setProperty("--color-foreground", "black");
  document.documentElement.style.setProperty("--color-muted-foreground", "grey");
  document.documentElement.style.setProperty("--color-warning", "orange");
});

afterEach(() => {
  vi.restoreAllMocks();
  size.width = 120;
});

/** Run the next `count` animation frames. */
function tick(count = 1, at = 16) {
  for (let i = 0; i < count; i++) frames.shift()?.(at * (i + 1));
}

describe("VoiceWaveform", () => {
  it("paints the caller's level in the theme's ink, hidden from screen readers", () => {
    const { context, fills } = fakeContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
    const { container } = render(<VoiceWaveform visual="user" levels={{ input: 1, output: 0 }} />);
    tick();
    expect(container.querySelector("canvas")).toHaveAttribute("aria-hidden", "true");
    // 120 px of 3 px bars with 3 px gaps is twenty bars, each painted once.
    expect(context.roundRect).toHaveBeenCalledTimes(20);
    expect(new Set(fills.map((fill) => fill.style))).toEqual(new Set(["black"]));
  });

  it("crossfades to the agent's muted ink as it speaks, and to the warning while an approval waits", () => {
    const { context, fills } = fakeContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
    const { rerender } = render(<VoiceWaveform visual="agent" levels={{ input: 0, output: 1 }} />);
    tick(60);
    expect(fills.at(-1)?.style).toBe("grey");
    rerender(<VoiceWaveform visual="approval" levels={{ input: 0, output: 0 }} />);
    tick(120);
    expect(fills.at(-1)?.style).toBe("orange");
  });

  it("reads the colours again when the theme changes, not on every frame", async () => {
    const { context, fills } = fakeContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
    const computed = vi.spyOn(window, "getComputedStyle");
    render(<VoiceWaveform visual="user" levels={{ input: 1, output: 0 }} />);
    tick(5);
    const reads = computed.mock.calls.length;
    expect(reads).toBe(3);
    document.documentElement.style.setProperty("--color-foreground", "white");
    document.documentElement.classList.add("dark");
    await Promise.resolve();
    tick();
    expect(fills.at(-1)?.style).toBe("white");
    document.documentElement.classList.remove("dark");
  });

  it("draws quiet bars faintly and never at less than three pixels", () => {
    const { context, fills } = fakeContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
    render(<VoiceWaveform visual="quiet" levels={{ input: 0, output: 0 }} />);
    tick();
    expect(fills[0]?.alpha).toBeCloseTo(0.3);
    expect(context.roundRect.mock.calls[0]?.[3]).toBe(3);
  });

  it("waits for a size, and gives no context nothing to do", () => {
    const { context } = fakeContext();
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(context as never);
    size.width = 0;
    const { unmount } = render(<VoiceWaveform visual="user" levels={{ input: 1, output: 0 }} />);
    tick();
    expect(context.roundRect).not.toHaveBeenCalled();
    unmount();
    expect(window.cancelAnimationFrame).toHaveBeenCalled();

    getContext.mockReturnValue(null);
    frames = [];
    render(<VoiceWaveform visual="user" levels={{ input: 1, output: 0 }} />);
    expect(frames).toHaveLength(0);
  });
});
