/**
 * The window a page of the desktop app is drawn in, as far as blobby needs it:
 * where it is, how big, on which monitor, where the cursor is, and moving it.
 *
 * Tauri's own JavaScript API, reached through its global and narrowed here to
 * the functions blobby calls, each checked to exist before it is used. The
 * shell grants exactly these to blobby's window (`console.rs`).
 */

import { ShellError } from "@/lib/desktop/shell";
import type { Area } from "@/lib/desktop/blobby-engine";

interface Point {
  x: number;
  y: number;
}

interface Size {
  width: number;
  height: number;
}

export interface DesktopWindow {
  /** Logical pixels: what a person's eye measures, whatever the display's density. */
  position: () => Promise<Point>;
  size: () => Promise<Size>;
  moveTo: (point: Point) => Promise<void>;
  startDragging: () => Promise<void>;
  /** The usable rectangle of the monitor the window is on, in logical pixels. */
  monitorArea: () => Promise<Area | null>;
  /** The cursor, in logical pixels on the desktop. */
  cursor: () => Promise<Point>;
  onMoved: (handler: (point: Point) => void) => Promise<() => void>;
}

type Fields = Record<string, unknown>;

function isFields(value: unknown): value is Fields {
  return typeof value === "object" && value !== null;
}

function fn(owner: Fields, name: string): (...args: unknown[]) => unknown {
  const value = owner[name];
  if (typeof value !== "function") throw new ShellError("unavailable", name);
  return (...args: unknown[]) => Reflect.apply(value, owner, args);
}

function point(value: unknown): Point {
  if (!isFields(value) || typeof value.x !== "number" || typeof value.y !== "number") {
    throw new ShellError("malformed", "position");
  }
  return { x: value.x, y: value.y };
}

function size(value: unknown): Size {
  if (!isFields(value) || typeof value.width !== "number" || typeof value.height !== "number") {
    throw new ShellError("malformed", "size");
  }
  return { width: value.width, height: value.height };
}

/** A monitor's usable rectangle in logical pixels, from the physical one Tauri reports. */
export function logicalArea(monitor: unknown): Area | null {
  if (!isFields(monitor) || typeof monitor.scaleFactor !== "number") return null;
  const area = isFields(monitor.workArea)
    ? monitor.workArea
    : { position: monitor.position, size: monitor.size };
  const scale = monitor.scaleFactor;
  const { x, y } = point(area.position);
  const { width, height } = size(area.size);
  return { x: x / scale, y: y / scale, width: width / scale, height: height / scale };
}

/** This page's window, or a `ShellError` outside the desktop app. */
export function currentWindow(): DesktopWindow {
  const api = typeof window === "undefined" ? undefined : window.__TAURI__;
  if (!isFields(api) || !isFields(api.window) || !isFields(api.dpi)) {
    throw new ShellError("unavailable", "window");
  }
  const tauriWindow = api.window;
  const handle = fn(tauriWindow, "getCurrentWindow")();
  if (!isFields(handle)) throw new ShellError("unavailable", "getCurrentWindow");
  const LogicalPosition = api.dpi.LogicalPosition;
  if (typeof LogicalPosition !== "function") throw new ShellError("unavailable", "LogicalPosition");
  const scale = async () => {
    const factor = await fn(handle, "scaleFactor")();
    return typeof factor === "number" && factor > 0 ? factor : 1;
  };
  return {
    position: async () => {
      const [outer, factor] = await Promise.all([fn(handle, "outerPosition")(), scale()]);
      const { x, y } = point(outer);
      return { x: x / factor, y: y / factor };
    },
    size: async () => {
      const [outer, factor] = await Promise.all([fn(handle, "outerSize")(), scale()]);
      const { width, height } = size(outer);
      return { width: width / factor, height: height / factor };
    },
    moveTo: async ({ x, y }) => {
      await fn(handle, "setPosition")(Reflect.construct(LogicalPosition, [x, y]));
    },
    startDragging: async () => {
      await fn(handle, "startDragging")();
    },
    monitorArea: async () => logicalArea(await fn(tauriWindow, "currentMonitor")()),
    cursor: async () => {
      const [cursor, factor] = await Promise.all([fn(tauriWindow, "cursorPosition")(), scale()]);
      const { x, y } = point(cursor);
      return { x: x / factor, y: y / factor };
    },
    onMoved: async (handler) => {
      const unlisten = await fn(
        handle,
        "onMoved",
      )(async (event: unknown) => {
        const factor = await scale();
        const { x, y } = point(isFields(event) ? event.payload : undefined);
        handler({ x: x / factor, y: y / factor });
      });
      if (typeof unlisten !== "function") throw new ShellError("malformed", "unlisten");
      return () => unlisten();
    },
  };
}
