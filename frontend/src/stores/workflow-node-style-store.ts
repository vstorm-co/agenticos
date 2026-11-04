"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/** How the workflow canvas draws a step: in its family's colour, or as plain neutral tiles. */
export type NodeStyle = "colour" | "simple";

interface WorkflowNodeStyleState {
  style: NodeStyle;
  setStyle: (style: NodeStyle) => void;
}

/**
 * How the workflow editor draws its steps - a person's taste, kept in this
 * browser like the theme. In colour by default; Simple is the neutral look the
 * canvas had before steps were drawn by family.
 */
export const useWorkflowNodeStyleStore = create<WorkflowNodeStyleState>()(
  persist(
    (set) => ({
      style: "colour",
      setStyle: (style) => set({ style }),
    }),
    { name: "workflow-node-style-storage" },
  ),
);
