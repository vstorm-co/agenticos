"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** One box to draw an edge for: its key in the ref map, and which side it hangs off. */
export interface EdgeInput {
  key: string;
  side: "in" | "out";
}

/** A measured edge, kept by node key so the focused node can pick its own out. */
export interface MapEdge {
  key: string;
  path: string;
}

/** How far the wheel and the buttons may take the scale, either way. */
const MIN_SCALE = 0.4;
const MAX_SCALE = 2.5;

/** A cubic curve between two points, flat at both ends so it meets the box square-on. */
function curve(from: { x: number; y: number }, to: { x: number; y: number }): string {
  const bend = Math.max(32, Math.abs(to.x - from.x) / 2);
  return `M ${from.x} ${from.y} C ${from.x + bend} ${from.y}, ${to.x - bend} ${to.y}, ${to.x} ${to.y}`;
}

/**
 * The map's geometry: where the edges land, and how pan and zoom move it.
 *
 * Its own hook because it is the half of the map that is not React - refs to real
 * elements, a ResizeObserver, and one transform standing in for a re-layout - and
 * separating it leaves the component to render nodes and hold which one is focused.
 *
 * The edges are measured rather than drawn at fixed coordinates: the boxes are
 * laid out by the browser (their height depends on how many things they list),
 * so a hand-placed curve would land in the middle of a box the moment somebody
 * attached a fourth skill - or a second delegate.
 */
export function useMapView(edgeInputs: EdgeInput[]) {
  const viewport = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const hub = useRef<HTMLDivElement>(null);
  const boxes = useRef(new Map<string, HTMLElement>());
  const [edges, setEdges] = useState<MapEdge[]>([]);

  // Pan and zoom as one transform on the content. The edges are measured in
  // the content's own coordinates, so the same transform carries them along
  // and nothing has to be re-measured while somebody drags.
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  // Mirrored into a ref so `measure` can read the newest scale without listing
  // `view` as a dependency - it does, and re-creating it would re-subscribe the
  // ResizeObserver on every step of a pinch.
  const viewRef = useRef(view);
  useLayoutEffect(() => {
    viewRef.current = view;
  }, [view]);
  const drag = useRef<{ pointerId: number; startX: number; startY: number } | null>(null);

  /** A stable ref-setter per key, registering and forgetting the box it draws to. */
  const registerBox = useCallback(
    (key: string) => (element: HTMLElement | null) => {
      if (element) boxes.current.set(key, element);
      else boxes.current.delete(key);
    },
    [],
  );

  const measure = useCallback(() => {
    const root = container.current;
    const centre = hub.current;
    /* v8 ignore next -- React has attached both refs before any effect runs */
    if (!root || !centre) return;

    // Rects are in screen space, which the transform has already scaled; the
    // paths render inside the transformed content, so divide back to local.
    const scale = viewRef.current.scale;
    const origin = root.getBoundingClientRect();
    const hubBox = centre.getBoundingClientRect();
    const paths: MapEdge[] = [];

    for (const node of edgeInputs) {
      const element = boxes.current.get(node.key);
      /* v8 ignore next -- every node renders a box and registers it by key */
      if (!element) continue;
      const box = element.getBoundingClientRect();
      const anchor = {
        x: ((node.side === "in" ? box.right : box.left) - origin.left) / scale,
        y: (box.top + box.height / 2 - origin.top) / scale,
      };
      const hubSide = {
        x: ((node.side === "in" ? hubBox.left : hubBox.right) - origin.left) / scale,
        y: (hubBox.top + hubBox.height / 2 - origin.top) / scale,
      };
      const path = node.side === "in" ? curve(anchor, hubSide) : curve(hubSide, anchor);
      paths.push({ key: node.key, path });
    }

    setEdges(paths);
  }, [edgeInputs]);

  useLayoutEffect(measure, [measure]);

  useEffect(() => {
    const root = container.current;
    /* v8 ignore next -- as above: the ref is set before this effect */
    if (!root) return;
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    for (const element of boxes.current.values()) observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

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

  const resetView = useCallback(() => setView({ x: 0, y: 0, scale: 1 }), []);

  // The wheel listener is attached by hand: React registers `onWheel` as
  // passive, and a passive listener cannot stop the dialog behind the map from
  // scrolling while somebody zooms.
  useEffect(() => {
    const element = viewport.current;
    /* v8 ignore next -- as above: the ref is set before this effect */
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

  return {
    viewport,
    container,
    hub,
    registerBox,
    edges,
    view,
    zoomFromCentre,
    resetView,
    panHandlers,
  };
}
