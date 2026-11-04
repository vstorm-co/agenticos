import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useBlobbyMotion } from "./use-blobby-motion";

const deps = vi.hoisted(() => ({
  win: null as null | FakeWindow,
  moved: (_point: { x: number; y: number }) => {},
  save: vi.fn(async () => {}),
  report: vi.fn(),
  random: [] as number[],
}));

vi.mock("@/lib/desktop/window", () => ({
  currentWindow: () => {
    if (!deps.win) throw new Error("unavailable: window");
    return deps.win;
  },
}));
vi.mock("@/lib/desktop/commands", () => ({ saveBlobbyPosition: deps.save }));
vi.mock("@/lib/desktop/shell", () => ({ reportShellFailure: deps.report }));

type FakeWindow = ReturnType<typeof makeWindow>;

function makeWindow() {
  return {
    position: vi.fn(async () => ({ x: 100, y: 500 })),
    size: vi.fn(async () => ({ width: 200, height: 232 })),
    monitorArea: vi.fn(
      async (): Promise<{ x: number; y: number; width: number; height: number } | null> => ({
        x: 0,
        y: 0,
        width: 1000,
        height: 800,
      }),
    ),
    moveTo: vi.fn(async () => {}),
    startDragging: vi.fn(async () => {}),
    cursor: vi.fn(async () => ({ x: 400, y: 600 })),
    onMoved: vi.fn(async (handler: (point: { x: number; y: number }) => void) => {
      deps.moved = handler;
      return () => {};
    }),
  };
}

const onQuip = vi.fn();
const options = (overrides = {}) => ({
  roams: true,
  chatter: "chatty" as const,
  still: false,
  onQuip,
  ...overrides,
});

/** Drive the frame loop: fake timers schedule `requestAnimationFrame` too. */
async function frames(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "requestAnimationFrame",
      "cancelAnimationFrame",
      "performance",
      "Date",
    ],
  });
  deps.win = makeWindow();
  deps.save.mockClear();
  deps.report.mockClear();
  onQuip.mockClear();
  vi.spyOn(Math, "random").mockReturnValue(0.8);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useBlobbyMotion", () => {
  it("strolls the window along the bottom of the screen once idling runs out", async () => {
    vi.setSystemTime(new Date("2026-10-21T12:00:00"));
    const { result } = renderHook(() => useBlobbyMotion(options()));
    await frames(5200);
    expect(result.current.state).toBe("stroll");
    expect(onQuip).not.toHaveBeenCalled();
    await frames(500);
    expect(deps.win!.moveTo).toHaveBeenCalled();
  });

  it("says something now and then, as often as it was asked to", async () => {
    vi.mocked(Math.random).mockReturnValue(0.1);
    renderHook(() => useBlobbyMotion(options()));
    await frames(5200);
    expect(onQuip).toHaveBeenCalled();
  });

  it("turns round at the edge of the monitor", async () => {
    vi.setSystemTime(new Date("2026-10-21T12:00:00"));
    deps.win!.position.mockResolvedValue({ x: 795, y: 500 });
    const { result } = renderHook(() => useBlobbyMotion(options()));
    await frames(5200);
    await frames(1000);
    expect(result.current.facing).toBe(-1);
  });

  it("keeps a window that was off the monitor on it", async () => {
    deps.win!.position.mockResolvedValue({ x: 990, y: 790 });
    renderHook(() => useBlobbyMotion(options({ still: true })));
    await frames(10);
    expect(deps.win!.moveTo).toHaveBeenCalledWith({ x: 800, y: 568 });
  });

  it("answers a reaction, then goes back to what it was doing", async () => {
    const { result } = renderHook(() => useBlobbyMotion(options()));
    act(() => result.current.react("wave", 1000));
    expect(result.current.state).toBe("wave");
    await frames(1100);
    expect(result.current.state).toBe("idle");
  });

  it("saves where it was dragged to, once the window comes to rest, and lands with a hop", async () => {
    const { result } = renderHook(() => useBlobbyMotion(options({ still: true })));
    await frames(10);
    act(() => result.current.startDragging());
    expect(deps.win!.startDragging).toHaveBeenCalled();
    deps.win!.position.mockResolvedValue({ x: 300, y: 400 });
    act(() => deps.moved({ x: 300, y: 400 }));
    await frames(500);
    expect(deps.save).toHaveBeenCalledWith(300, 400);
    expect(result.current.state).toBe("hop");
  });

  it("follows the cursor with its eyes while it stands about", async () => {
    const { result } = renderHook(() => useBlobbyMotion(options()));
    await frames(300);
    expect(result.current.gaze).toEqual({ x: 300, y: 100 });
  });

  it("holds still - and stands - under reduced motion or with nobody signed in", async () => {
    const { result } = renderHook(() => useBlobbyMotion(options({ still: true })));
    await frames(20000);
    expect(result.current.state).toBe("idle");
    expect(deps.win!.cursor).not.toHaveBeenCalled();
  });

  it("reports a page with no window rather than crashing", () => {
    deps.win = null;
    renderHook(() => useBlobbyMotion(options({ still: true })));
    expect(deps.report).toHaveBeenCalledWith("blobby has no window", expect.any(Error));
  });

  it("saves a move it did not start without a hop, and stays on a monitor it cannot measure", async () => {
    deps.win!.monitorArea.mockResolvedValue(null);
    const { result } = renderHook(() => useBlobbyMotion(options({ still: true })));
    await frames(10);
    act(() => deps.moved({ x: 5000, y: 5000 }));
    deps.win!.position.mockResolvedValue({ x: 5000, y: 5000 });
    await frames(500);
    expect(deps.save).toHaveBeenCalledWith(5000, 5000);
    expect(deps.win!.moveTo).not.toHaveBeenCalled();
    expect(result.current.state).toBe("idle");
  });

  it("stands when it is held still in the middle of a stroll", async () => {
    vi.setSystemTime(new Date("2026-10-21T12:00:00"));
    const { result, rerender } = renderHook(
      (props: { still: boolean }) => useBlobbyMotion(options(props)),
      {
        initialProps: { still: false },
      },
    );
    await frames(5200);
    expect(result.current.state).toBe("stroll");
    rerender({ still: true });
    expect(result.current.state).toBe("idle");
  });

  it("stops following a window whose listener arrives after it has gone", async () => {
    const stop = vi.fn();
    let resolve: (stop: () => void) => void = () => {};
    deps.win!.onMoved.mockReturnValue(new Promise((r) => (resolve = r)));
    const { unmount } = renderHook(() => useBlobbyMotion(options({ still: true })));
    unmount();
    resolve(stop);
    await frames(10);
    expect(stop).toHaveBeenCalled();
  });

  it("reports every window call the shell refuses, and keeps going", async () => {
    vi.setSystemTime(new Date("2026-10-21T12:00:00"));
    const refuse = () => Promise.reject(new Error("refused"));
    deps.win!.moveTo.mockImplementation(refuse);
    deps.win!.startDragging.mockImplementation(refuse);
    deps.win!.cursor.mockImplementation(refuse);
    deps.win!.position.mockResolvedValueOnce({ x: 2000, y: 500 });
    const { result } = renderHook(() => useBlobbyMotion(options()));
    await frames(5500);
    act(() => result.current.startDragging());
    await frames(10);
    deps.win!.size.mockImplementation(refuse);
    act(() => deps.moved({ x: 1, y: 1 }));
    await frames(500);
    const said = deps.report.mock.calls.map(([what]) => what);
    for (const what of [
      "could not place blobby",
      "could not find the cursor",
      "could not drag blobby",
      "could not walk blobby",
      "could not keep blobby's place",
    ]) {
      expect(said).toContain(what);
    }
  });

  it("reports a window it cannot follow", async () => {
    deps.win!.onMoved.mockRejectedValue(new Error("refused"));
    renderHook(() => useBlobbyMotion(options({ still: true })));
    await frames(10);
    expect(deps.report).toHaveBeenCalledWith("could not follow blobby's window", expect.any(Error));
  });
});
