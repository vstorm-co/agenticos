import { ownsAScope } from "@/components/workflows/palette";
import { ERROR_PORT, routesErrors } from "@/lib/workflows/ports";
import type { Binding, NodeDefinition, NodeInstance } from "@/lib/workflows/types";

import { waitsBand } from "./waits-band";

/** The footprint a step's card takes on the canvas by default, for placement only. */
export const NODE_WIDTH = 240;
export const NODE_HEIGHT = 88;
/** What a person may resize a step to. The height's floor is the card's own natural height. */
export const MIN_NODE_WIDTH = 200;
export const MAX_NODE_WIDTH = 560;
export const MAX_NODE_HEIGHT = 400;

/** A step's width and height as the canvas draws it. */
export interface Footprint {
  width: number;
  height: number;
}

/** What one extra line of text costs a card, in pixels: the name's line, the summary's. */
const NAME_LINE = 20;
const SUMMARY_LINE = 16;

/**
 * How tall a step's card is before anyone resizes it, worked out from its classes:
 * the head - border, padding, label and name, 60 px - plus a summary or resource
 * line (16), a waits band, the labelled output rows, the policy badges (which wrap
 * once there are three) and a loop's "enter" row, where the step has them.
 * `hasTextLine` is whether the card draws that line; placement does not know and
 * leaves it on, a little over rather than under.
 */
export function cardHeight(
  instance: NodeInstance,
  definition: NodeDefinition | null,
  bindings: readonly Binding[],
  hasTextLine = true,
): number {
  let height = hasTextLine ? 76 : 60;
  if (waitsBand(instance, bindings) !== null) height += 22;
  const outputs = definition?.ports.filter((port) => port.kind === "output") ?? [];
  if (outputs.length > 1 || outputs.some((port) => port.id === ERROR_PORT)) {
    height += 13 + outputs.length * 16 + (outputs.length - 1) * 2;
  }
  const policy = instance.policy;
  const badges =
    (policy?.timeout_seconds ? 1 : 0) +
    ((policy?.retry?.max_attempts ?? 1) > 1 ? 1 : 0) +
    (routesErrors(instance) ? 1 : 0);
  if (badges > 0) height += 28.5 + (badges >= 3 ? 22.5 : 0);
  if (definition !== null && ownsAScope(definition)) height += 45;
  return height;
}

/** A step's footprint on the canvas: the size it was given, else the default and its natural height. */
export function stepFootprint(
  instance: NodeInstance,
  definition: NodeDefinition | null,
  bindings: readonly Binding[],
): Footprint {
  return {
    width: instance.layout.width ?? NODE_WIDTH,
    height: instance.layout.height ?? cardHeight(instance, definition, bindings),
  };
}

/**
 * How many lines of text a card of `height` gives its name and its summary. The
 * extra height over `natural` goes to the name first - up to three lines - and
 * then to the summary, up to two; an unsized card has none and keeps one each.
 */
export function textLines(
  height: number | null | undefined,
  natural: number,
): { name: 1 | 2 | 3; summary: 1 | 2 } {
  const extra = height == null ? 0 : Math.max(0, height - natural);
  const name = Math.min(3, 1 + Math.floor(extra / NAME_LINE)) as 1 | 2 | 3;
  // The summary gets only what is left once the name has its three lines.
  const left = Math.max(0, extra - 2 * NAME_LINE);
  const summary = Math.min(2, 1 + Math.floor(left / SUMMARY_LINE)) as 1 | 2;
  return { name, summary };
}
