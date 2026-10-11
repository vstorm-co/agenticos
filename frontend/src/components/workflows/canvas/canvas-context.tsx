"use client";

import { createContext, useContext } from "react";

import type { StepChange } from "@/lib/workflows/graph-diff";
import type { NodeDefinition } from "@/lib/workflows/types";

/** One end of a keyboard-driven connection: a node and one of its ports. */
export interface ConnectEndpoint {
  nodeId: string;
  portId: string;
}

/**
 * The canvas interaction a node component needs but `@xyflow/react` does not
 * carry in `data`: the read-only flag and the keyboard connect-mode handlers.
 *
 * Connect mode is the accessible substitute for a pointer drag: a node's output
 * starts a connection (`beginConnect`), and another node's input completes it
 * (`completeConnect`, given the pending source and its own endpoint), each a real
 * button rather than a handle only a mouse can reach. `connectSource` is the
 * pending source while a connection is in progress — non-null exactly when a
 * node may show its "complete" control. `insertAfter` is what a node's "+"
 * beside an output calls: the next step, placed and wired in one change.
 */
export interface CanvasInteraction {
  readOnly: boolean;
  connectSource: ConnectEndpoint | null;
  beginConnect: (endpoint: ConnectEndpoint) => void;
  completeConnect: (source: ConnectEndpoint, target: ConnectEndpoint) => void;
  /** The node catalog a node's "+" offers the next step from. */
  catalog: NodeDefinition[];
  /** Add `definition` after `nodeId`'s `portId`, wired to it. */
  insertAfter: (nodeId: string, portId: string, definition: NodeDefinition) => void;
  /** How many problems each node has that stop publishing - a node with none is absent. */
  problemCounts: ReadonlyMap<string, number>;
  /** When two versions are compared: how each step differs - one the same is absent. */
  changes?: ReadonlyMap<string, StepChange>;
}

const CanvasInteractionContext = createContext<CanvasInteraction | null>(null);

export const CanvasInteractionProvider = CanvasInteractionContext.Provider;

/** The interaction context, or a hard error when a node renders outside the canvas. */
export function useCanvasInteraction(): CanvasInteraction {
  const value = useContext(CanvasInteractionContext);
  if (value === null) {
    throw new Error("useCanvasInteraction must be used within a CanvasInteractionProvider");
  }
  return value;
}
