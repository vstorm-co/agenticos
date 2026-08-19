"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * A side panel the reader drags to the width they want, remembered per panel.
 *
 * One implementation, because there are two panels now - the chat's attachment
 * preview and the run detail - and a second copy of a pointer-capture loop is a
 * second place for the drag to stop releasing the cursor. The caller owns the
 * markup; this owns the width and the drag.
 *
 * The stored width is read once, as the initial state, rather than written back
 * from an effect: that rendered the panel at its default and snapped it to the
 * remembered width a frame later. Reading `localStorage` during render is safe
 * here because a panel renders nothing until the reader opens one, and nothing
 * opens one on the server - there is no first paint to disagree with.
 */
export interface ResizablePanel {
  /** The current width in pixels. The caller applies it, and only above `lg`. */
  width: number;
  /** True while the reader is dragging - for the handle's own highlight. */
  isDragging: boolean;
  /** Put this on the drag handle. */
  onMouseDown: (event: React.MouseEvent) => void;
  /**
   * Widen or narrow by `delta` pixels, clamped and remembered.
   *
   * What the arrow keys call. A boundary that can only be dragged is a boundary
   * somebody navigating by keyboard cannot move at all, and the panel it sizes
   * is where they would be reading a transcript.
   */
  resizeBy: (delta: number) => void;
}

export function useResizablePanel({
  storageKey,
  defaultWidth,
  min,
  max,
}: {
  storageKey: string;
  defaultWidth: number;
  min: number;
  max: number;
}): ResizablePanel {
  const [width, setWidth] = useState<number>(() => stored(storageKey, defaultWidth, min, max));
  const [isDragging, setIsDragging] = useState(false);

  const onMouseDown = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (event: MouseEvent) => {
      // Width is the distance from the cursor to the right edge of the viewport.
      setWidth(clamp(window.innerWidth - event.clientX, min, max));
    };
    const onUp = () => {
      setIsDragging(false);
      try {
        localStorage.setItem(storageKey, String(width));
      } catch {
        /* private mode, or quota - drop the persistence rather than the drag */
      }
    };
    // On the body, so the cursor and the selection behave over the whole window
    // rather than only over the handle the drag started on.
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [isDragging, width, storageKey, min, max]);

  const resizeBy = useCallback(
    (delta: number) => {
      setWidth((current) => {
        const next = clamp(current + delta, min, max);
        try {
          localStorage.setItem(storageKey, String(next));
        } catch {
          /* private mode, or quota - drop the persistence rather than the resize */
        }
        return next;
      });
    },
    [storageKey, min, max],
  );

  return { width, isDragging, onMouseDown, resizeBy };
}

function stored(key: string, fallback: number, min: number, max: number): number {
  /* v8 ignore next -- an SSR guard, and the test environment is jsdom */
  if (typeof window === "undefined") return fallback;
  const remembered = parseInt(localStorage.getItem(key) ?? "", 10);
  return Number.isFinite(remembered) ? clamp(remembered, min, max) : fallback;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
