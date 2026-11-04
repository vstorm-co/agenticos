"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** How far the wheel and the buttons may take the scale, either way. */
const MIN_SCALE = 0.4;
const MAX_SCALE = 2.5;

export interface View {
  x: number;
  y: number;
  scale: number;
}

const HOME: View = { x: 0, y: 0, scale: 1 };

/** What a press starts by itself rather than a drag of the canvas. */
const CONTROLS = "button, a, input, select, textarea, label, [role='button']";

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
  const drag = useRef<{ pointerId: number; startX: number; startY: number } | null>(null);

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

  const panHandlers = {
    onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => {
      // Capturing the pointer retargets its release to the canvas, so the click a
      // control under it was pressed for would never reach that control.
      if ((event.target as Element).closest(CONTROLS)) return;
      drag.current = {
        pointerId: event.pointerId,
        startX: event.clientX - view.x,
        startY: event.clientY - view.y,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    onPointerMove: (event: React.PointerEvent<HTMLDivElement>) => {
      const active = drag.current;
      if (!active || active.pointerId !== event.pointerId) return;
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
