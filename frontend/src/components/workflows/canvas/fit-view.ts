import type { FitViewOptions } from "@xyflow/react";

/** Frame the whole graph, but no smaller than a node's text stays legible at. */
const FIT_VIEW = { padding: 0.2, minZoom: 0.55, maxZoom: 1 };
/** A read-only graph is looked at whole - a run, a past version - so it may shrink further. */
const FIT_VIEW_READ_ONLY = { padding: 0.15, minZoom: 0.5, maxZoom: 1 };
/**
 * A phone holds a few hundred pixels: at the legibility floor a flow of three steps
 * already runs off both edges, so the first look shows all of it and pinching reads it.
 */
// The graph determines its overview scale; a fixed floor clips longer flows.
const NARROW_MIN_ZOOM = 0;
/** How far the builder may zoom out by hand. */
const MIN_ZOOM = 0.3;

/** How the canvas frames its graph on entry. */
export function fitViewOptions(readOnly: boolean, narrow: boolean): FitViewOptions {
  const base = readOnly ? FIT_VIEW_READ_ONLY : FIT_VIEW;
  return narrow ? { ...base, minZoom: NARROW_MIN_ZOOM } : base;
}

/** The furthest out the canvas lets anyone zoom - never past what its own framing used. */
export function minZoomFor(narrow: boolean): number {
  return narrow ? NARROW_MIN_ZOOM : MIN_ZOOM;
}
