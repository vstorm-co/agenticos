import { afterEach, describe, expect, it, vi } from "vitest";

import { currentWindow, logicalArea } from "./window";

class LogicalPosition {
  constructor(
    readonly x: number,
    readonly y: number,
  ) {}
}

function fakeWindow(overrides: Record<string, unknown> = {}) {
  const handle = {
    scaleFactor: vi.fn(async () => 2),
    outerPosition: vi.fn(async () => ({ x: 400, y: 200 })),
    outerSize: vi.fn(async () => ({ width: 400, height: 464 })),
    setPosition: vi.fn(async () => {}),
    startDragging: vi.fn(async () => {}),
    onMoved: vi.fn(async () => () => {}),
    ...overrides,
  };
  window.__TAURI__ = {
    window: {
      getCurrentWindow: () => handle,
      currentMonitor: async () => ({
        scaleFactor: 2,
        workArea: { position: { x: 0, y: 50 }, size: { width: 3000, height: 1800 } },
      }),
      cursorPosition: async () => ({ x: 1000, y: 600 }),
    },
    dpi: { LogicalPosition },
  };
  return handle;
}

afterEach(() => {
  delete window.__TAURI__;
});

describe("currentWindow", () => {
  it("speaks logical pixels whatever the display's density", async () => {
    fakeWindow();
    const win = currentWindow();
    await expect(win.position()).resolves.toEqual({ x: 200, y: 100 });
    await expect(win.size()).resolves.toEqual({ width: 200, height: 232 });
    await expect(win.cursor()).resolves.toEqual({ x: 500, y: 300 });
    await expect(win.monitorArea()).resolves.toEqual({ x: 0, y: 25, width: 1500, height: 900 });
  });

  it("moves and drags the window, and follows its moves in logical pixels", async () => {
    let moved: (event: unknown) => Promise<void> = async () => {};
    const stop = vi.fn();
    const handle = fakeWindow({
      onMoved: vi.fn(async (handler: typeof moved) => {
        moved = handler;
        return stop;
      }),
    });
    const win = currentWindow();
    await win.moveTo({ x: 10, y: 20 });
    expect(handle.setPosition).toHaveBeenCalledWith(new LogicalPosition(10, 20));
    await win.startDragging();
    expect(handle.startDragging).toHaveBeenCalled();
    const seen = vi.fn();
    const unlisten = await win.onMoved(seen);
    await moved({ payload: { x: 300, y: 100 } });
    await expect(moved(null)).rejects.toThrow("malformed: position");
    expect(seen).toHaveBeenCalledWith({ x: 150, y: 50 });
    unlisten();
    expect(stop).toHaveBeenCalled();
  });

  it("takes a nonsensical scale factor as 1", async () => {
    fakeWindow({ scaleFactor: async () => 0 });
    await expect(currentWindow().position()).resolves.toEqual({ x: 400, y: 200 });
  });

  it("refuses a page outside the app and an API missing what it needs", async () => {
    expect(() => currentWindow()).toThrow("unavailable");
    window.__TAURI__ = { window: { getCurrentWindow: () => null }, dpi: { LogicalPosition } };
    expect(() => currentWindow()).toThrow("unavailable: getCurrentWindow");
    window.__TAURI__ = { window: { getCurrentWindow: () => ({}) }, dpi: {} };
    expect(() => currentWindow()).toThrow("unavailable: LogicalPosition");
    fakeWindow({ startDragging: undefined });
    await expect(currentWindow().startDragging()).rejects.toThrow("unavailable: startDragging");
  });

  it("refuses answers that are not positions, sizes or unlistens", async () => {
    fakeWindow({
      outerPosition: async () => ({ x: "1" }),
      outerSize: async () => null,
      onMoved: async () => 1,
    });
    const win = currentWindow();
    await expect(win.position()).rejects.toThrow("malformed: position");
    await expect(win.size()).rejects.toThrow("malformed: size");
    await expect(win.onMoved(() => {})).rejects.toThrow("malformed: unlisten");
  });
});

describe("logicalArea", () => {
  it("falls back to the whole monitor without a work area, and to nothing without a monitor", () => {
    expect(
      logicalArea({ scaleFactor: 1, position: { x: 5, y: 6 }, size: { width: 7, height: 8 } }),
    ).toEqual({ x: 5, y: 6, width: 7, height: 8 });
    expect(logicalArea(null)).toBeNull();
    expect(logicalArea({ position: {} })).toBeNull();
  });
});
