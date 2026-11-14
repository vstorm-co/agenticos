"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** How far the wheel and the buttons may take the scale, either way. */
const MIN_SCALE = 0.15;
const MAX_SCALE = 2.5;

export interface View {
  x: number;
  y: number;
  scale: number;
}

const HOME: View = { x: 0, y: 0, scale: 1 };

/** How far a press moves before it is a drag rather than a click, in screen pixels. */
const DRAG_THRESHOLD = 4;

/**
 * Pan and zoom over a diagram drawn in its own coordinates: one transform on the
 * content, dragged with the pointer and zoomed with the wheel or the buttons.
 *
 * Nothing under the transform is laid out again while somebody drags, so edges
 * measured in the content's coordinates move with it. `home` is where Reset view
 * goes, and where the view starts.
 */
export function usePanZoom(home: View = HOME) {
  const viewport = useRef<HTMLDivElement>(null);
  const [view, setView] = useState(home);
  // Mirrored into a ref so a measurement can read the newest scale without
  // listing `view` as a dependency and re-subscribing on every step of a pinch.
  const viewRef = useRef(view);
  useLayoutEffect(() => {
    viewRef.current = view;
  }, [view]);
  const drag = useRef<{
    pointerId: number;
    originX: number;
    originY: number;
    startX: number;
    startY: number;
    moving: boolean;
  } | null>(null);

  /** Zoom keeping the given viewport point still - the cursor, or the centre. */
  const zoomAt = useCallback((point: { x: number; y: number }, factor: number) => {
    setView((current) => {
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, current.scale * factor));
      const ratio = scale / current.scale;
      return {
        scale,
        x: point.x - (point.x - current.x) * ratio,
        y: point.y - (point.y - current.y) * ratio,
      };
    });
  }, []);

  const zoomFromCentre = useCallback(
    (factor: number) => {
      const box = viewport.current?.getBoundingClientRect();
      if (box) zoomAt({ x: box.width / 2, y: box.height / 2 }, factor);
    },
    [zoomAt],
  );

  const { x, y, scale } = home;
  const resetView = useCallback(() => setView({ x, y, scale }), [x, y, scale]);

  // The wheel listener is attached by hand: React registers `onWheel` as
  // passive, and a passive listener cannot stop the page behind from scrolling.
  useEffect(() => {
    const element = viewport.current;
    /* v8 ignore next -- the ref is set before this effect */
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const box = element.getBoundingClientRect();
      zoomAt(
        { x: event.clientX - box.left, y: event.clientY - box.top },
        event.deltaY < 0 ? 1.15 : 1 / 1.15,
      );
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  // A press below the threshold is not captured, so its release can land outside the
  // canvas; the page hears it either way, and a later move must not pan unpressed.
  useEffect(() => {
    const release = () => {
      drag.current = null;
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    return () => {
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
    };
  }, []);

  const panHandlers = {
    onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => {
      drag.current = {
        pointerId: event.pointerId,
        originX: event.clientX,
        originY: event.clientY,
        startX: event.clientX - view.x,
        startY: event.clientY - view.y,
        moving: false,
      };
    },
    onPointerMove: (event: React.PointerEvent<HTMLDivElement>) => {
      const active = drag.current;
      if (!active || active.pointerId !== event.pointerId) return;
      // The pointer is captured only once the press moves, so a press that stays put
      // is still a click on the node or control under it, and a drag from one pans.
      if (!active.moving) {
        const moved = Math.hypot(event.clientX - active.originX, event.clientY - active.originY);
        if (moved < DRAG_THRESHOLD) return;
        active.moving = true;
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      setView((current) => ({
        ...current,
        x: event.clientX - active.startX,
        y: event.clientY - active.startY,
      }));
    },
    onPointerUp: () => {
      drag.current = null;
    },
    onPointerCancel: () => {
      drag.current = null;
    },
  };

  return { viewport, view, setView, viewRef, zoomFromCentre, resetView, panHandlers };
}
