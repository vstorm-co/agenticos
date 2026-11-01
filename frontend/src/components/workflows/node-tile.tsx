"use client";

import {
  groupVisual,
  nodeVisual,
  operationVisual,
  type NodeVisual,
} from "@/components/workflows/node-visuals";
import { cn } from "@/lib/utils";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";

type Which =
  | { kind?: "step" | "operation"; definitionId: string; category: string }
  | { kind: "group"; category: string };

type NodeTileProps = Which & {
  /** The tile's size and corners; the family's own shape (a round Start) wins over them. */
  className: string;
  iconClassName: string;
};

/** The visual a tile draws, in the person's chosen style. */
function useNodeVisual(props: Which): NodeVisual {
  const style = useWorkflowNodeStyleStore((state) => state.style);
  if (props.kind === "group") return groupVisual(props.category, style);
  const draw = props.kind === "operation" ? operationVisual : nodeVisual;
  return draw(props.definitionId, props.category, style);
}

/**
 * A step's icon tile, wherever the editor draws one - the card, the picker, the
 * settings dialog - in its family's colour or, in Simple, neutral. One component
 * reading the person's style, so no caller subscribes to it on its own.
 */
export function NodeTile({ className, iconClassName, ...which }: NodeTileProps) {
  const visual = useNodeVisual(which);
  const Icon = visual.icon;
  return (
    <span
      data-node-family={visual.family}
      className={cn("flex shrink-0 items-center justify-center", className, visual.tileClass)}
    >
      <Icon aria-hidden="true" className={iconClassName} />
    </span>
  );
}
