"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { usePanZoom } from "@/hooks/use-pan-zoom";

/**
 * Which side of the agent a box hangs off (#518). Each answers its own
 * question: left is what reaches the agent, top is what it runs as, right is
 * what it reaches for, bottom is what it hands work to.
 */
export type MapSide = "left" | "right" | "top" | "bottom";

/** One box to draw an edge for: its key in the ref map, and which side it hangs off. */
export interface EdgeInput {
  key: string;
  side: MapSide;
}

/** A measured edge, kept by node key so the focused node can pick its own out. */
export interface MapEdge {
  key: string;
  path: string;
}

/** A cubic curve between two points, flat at both ends so it meets the box square-on. */
function curve(from: { x: number; y: number }, to: { x: number; y: number }): string {
  const bend = Math.max(32, Math.abs(to.x - from.x) / 2);
  return `M ${from.x} ${from.y} C ${from.x + bend} ${from.y}, ${to.x - bend} ${to.y}, ${to.x} ${to.y}`;
}

/** The same curve turned vertical, for a box above or below the hub. */
function verticalCurve(from: { x: number; y: number }, to: { x: number; y: number }): string {
  const bend = Math.max(32, Math.abs(to.y - from.y) / 2);
  return `M ${from.x} ${from.y} C ${from.x} ${from.y + bend}, ${to.x} ${to.y - bend}, ${to.x} ${to.y}`;
}

/**
 * The map's geometry: where the edges land, under the pan and zoom of `usePanZoom`.
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
  const container = useRef<HTMLDivElement>(null);
  const hub = useRef<HTMLDivElement>(null);
  const boxes = useRef(new Map<string, HTMLElement>());
  const [edges, setEdges] = useState<MapEdge[]>([]);

  // Named as a ref so the compiler reads `.current` below as one, not as a dependency.
  const {
    viewport: viewportRef,
    view,
    setView,
    viewRef,
    zoomFromCentre,
    panHandlers,
  } = usePanZoom();

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

    // Everything below is in the content's local coordinates.
    const local = (x: number, y: number) => ({
      x: (x - origin.left) / scale,
      y: (y - origin.top) / scale,
    });

    for (const node of edgeInputs) {
      const element = boxes.current.get(node.key);
      /* v8 ignore next -- every node renders a box and registers it by key */
      if (!element) continue;
      const box = element.getBoundingClientRect();

      // Each side anchors on the face looking at the hub, and the edge flows
      // the way the data does: into the agent from the left and the top, out
      // of it to the right and the bottom.
      let path: string;
      switch (node.side) {
        case "left":
          path = curve(
            local(box.right, box.top + box.height / 2),
            local(hubBox.left, hubBox.top + hubBox.height / 2),
          );
          break;
        case "right":
          path = curve(
            local(hubBox.right, hubBox.top + hubBox.height / 2),
            local(box.left, box.top + box.height / 2),
          );
          break;
        case "top":
          path = verticalCurve(
            local(box.left + box.width / 2, box.bottom),
            local(hubBox.left + hubBox.width / 2, hubBox.top),
          );
          break;
        case "bottom":
          path = verticalCurve(
            local(hubBox.left + hubBox.width / 2, hubBox.bottom),
            local(box.left + box.width / 2, box.top),
          );
          break;
      }
      paths.push({ key: node.key, path });
    }

    setEdges(paths);
  }, [edgeInputs, viewRef]);

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

  // Fit on opening and on actual layout changes, never while the person pans.
  const resetView = useCallback(() => {
    const frame = viewportRef.current;
    const content = container.current;
    if (!frame || !content || !frame.clientWidth || !content.offsetHeight) {
      setView({ x: 0, y: 0, scale: 1 });
      return;
    }
    const scale = Math.min(
      1,
      (frame.clientWidth - 32) / content.offsetWidth,
      (frame.clientHeight - 32) / content.offsetHeight,
    );
    setView({
      scale,
      x: (frame.clientWidth - content.offsetWidth * scale) / 2,
      y: (frame.clientHeight - content.offsetHeight * scale) / 2,
    });
  }, [viewportRef, setView]);

  useLayoutEffect(() => {
    resetView();
    const observer = new ResizeObserver(resetView);
    if (viewportRef.current) observer.observe(viewportRef.current);
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, [viewportRef, resetView]);

  return {
    viewport: viewportRef,
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
