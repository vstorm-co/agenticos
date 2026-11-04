import type { DragEvent } from "react";

import type { Uuid } from "./types";

/** The drag type a step's field travels under, from the Input pane to a setting. */
const FIELD_MIME = "application/x-agenticos-step-field";

/** One field of an earlier step's output, dragged onto a setting to be read from there. */
export interface DraggedField {
  nodeId: Uuid;
  path: string[];
  /** The JSON type the field held in the run it was dragged from. */
  type: string;
}

export function startFieldDrag(event: DragEvent, field: DraggedField): void {
  event.dataTransfer.setData(FIELD_MIME, JSON.stringify(field));
  event.dataTransfer.effectAllowed = "link";
}

/** Whether a drag carries a step's field - known while it is over a target, before the drop. */
export function carriesField(event: DragEvent): boolean {
  return Array.from(event.dataTransfer.types).includes(FIELD_MIME);
}

/** The field a drop carries, or null for anything else dropped. */
export function droppedField(event: DragEvent): DraggedField | null {
  const raw = event.dataTransfer.getData(FIELD_MIME);
  if (raw === "") return null;
  const parsed: unknown = JSON.parse(raw);
  if (typeof parsed !== "object" || parsed === null) return null;
  const { nodeId, path, type } = parsed as Record<string, unknown>;
  return typeof nodeId === "string" &&
    typeof type === "string" &&
    Array.isArray(path) &&
    path.every((part) => typeof part === "string")
    ? { nodeId, path, type }
    : null;
}

/** The JSON type a value takes for a field of each schema `type`. */
const TAKES: Record<string, string> = {
  string: "string",
  integer: "number",
  number: "number",
  boolean: "boolean",
  array: "array",
  object: "object",
};

/**
 * Whether a value of JSON type `observed` fits a field whose schema declares
 * `declared` - what a free-form source cannot say until a run has shown it.
 */
export function observedFits(declared: unknown, observed: string): boolean {
  const takes = typeof declared === "string" ? TAKES[declared] : undefined;
  return takes === undefined || takes === observed;
}

/** How near a scrolling area's top or bottom a drag starts scrolling it, in pixels. */
const EDGE = 56;
/** The most one dragover scrolls by - right at the edge. */
const FASTEST = 24;

/**
 * Scroll the area a drag is over when the pointer nears its top or bottom - a
 * browser does not scroll on the wheel while it carries a drag, so a setting
 * below the fold could not be reached. Faster the nearer the edge; called on
 * every dragover, which a browser keeps firing while the pointer rests.
 */
export function scrollNearEdge(event: DragEvent): void {
  let area = event.target as HTMLElement | null;
  while (area !== null && !scrolls(area)) area = area.parentElement;
  if (area === null) return;
  const { top, bottom } = area.getBoundingClientRect();
  const fromTop = event.clientY - top;
  const fromBottom = bottom - event.clientY;
  if (fromTop < EDGE) area.scrollTop -= Math.ceil(((EDGE - fromTop) / EDGE) * FASTEST);
  else if (fromBottom < EDGE) area.scrollTop += Math.ceil(((EDGE - fromBottom) / EDGE) * FASTEST);
}

function scrolls(element: HTMLElement): boolean {
  return (
    element.scrollHeight > element.clientHeight &&
    /(auto|scroll)/.test(getComputedStyle(element).overflowY)
  );
}
