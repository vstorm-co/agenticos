"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { isAddableInScope } from "@/components/workflows/palette/scope";
import { NodePicker } from "@/components/workflows/picker";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import type { NodeDefinition } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

interface QuickAddProps {
  /** The node catalog the menu offers steps from. */
  catalog: NodeDefinition[];
  /** What the "+" sits beside, for its label: the step's name and the port's. */
  nodeName: string;
  portLabel: string;
  /** Add the chosen step after this output. */
  onPick: (definition: NodeDefinition) => void;
  /** Always shown when nothing leaves the port yet; otherwise on hover and focus. */
  prominent: boolean;
}

/**
 * The "+" beside a node's output: the step picker, for the step that comes
 * next, added after this output and wired to it in one click.
 *
 * Only steps with an input are offered - a starting step cannot follow another -
 * and only those the scope in view allows, the palette's own rule.
 */
export function QuickAdd({ catalog, nodeName, portLabel, onPick, prominent }: QuickAddProps) {
  const t = useTranslations("workflows");
  const scopePath = useWorkflowEditorStore((state) => state.scopePath);
  const [open, setOpen] = useState(false);
  const offered = useMemo(
    () =>
      catalog.filter(
        (definition) =>
          definition.ports.some((port) => port.kind === "input") &&
          isAddableInScope(definition, scopePath),
      ),
    [catalog, scopePath],
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("quickAdd", { name: nodeName, port: portLabel })}
          // A button on the card, not a click on the node: xyflow would select it.
          onClick={(event) => event.stopPropagation()}
          className={cn(
            "nodrag nopan bg-background text-muted-foreground hover:text-foreground hover:border-foreground/40 focus-visible:ring-ring flex size-5 items-center justify-center rounded-full border shadow-sm transition-opacity outline-none focus-visible:ring-2",
            prominent || open
              ? "opacity-100"
              : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
          )}
        >
          <Plus aria-hidden="true" className="size-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80 p-0"
        align="start"
        side="right"
        onClick={(event) => event.stopPropagation()}
        // Focus goes to the step just added, not back to a "+" that has done its job.
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        <NodePicker
          offered={offered}
          onPick={(definition) => {
            onPick(definition);
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
