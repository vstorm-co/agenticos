"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useMemo, useState } from "react";

import { isAddableInScope } from "@/components/workflows/palette/scope";
import { NodePicker } from "@/components/workflows/picker";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import type { NodeDefinition } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/** A step this output already leads to, and the connection that leads there. */
export interface QuickAddNext {
  edgeId: string;
  name: string;
}

interface QuickAddProps {
  /** The node catalog the menu offers steps from. */
  catalog: NodeDefinition[];
  /** What the "+" sits beside, for its label: the step's name and the port's. */
  nodeName: string;
  portLabel: string;
  /** The steps this output already leads to - none when nothing leaves it yet. */
  next: readonly QuickAddNext[];
  /**
   * Add the chosen step after this output: into the connection `beforeEdgeId` names,
   * or beside what follows already when it is absent.
   */
  onPick: (
    definition: NodeDefinition,
    config?: Record<string, unknown>,
    beforeEdgeId?: string,
  ) => void;
}

/**
 * The "+" beside a node's output: the step picker, for the step that comes
 * next, added after this output and wired to it in one click.
 *
 * Only steps with an input are offered - a starting step cannot follow another -
 * and only those the scope in view allows, the palette's own rule.
 *
 * An output that already leads to one step asks where the new one goes: into that
 * connection, before the step it leads to, or beside it as a branch that runs too.
 * One that leads to several can only take another branch - "before" would not say
 * which.
 */
export function QuickAdd({ catalog, nodeName, portLabel, next, onPick }: QuickAddProps) {
  const t = useTranslations("workflows");
  const scopePath = useWorkflowEditorStore((state) => state.scopePath);
  const [open, setOpen] = useState(false);
  const [branch, setBranch] = useState(false);
  const only = next.length === 1 ? next[0] : undefined;
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
          aria-label={t(next.length === 0 ? "quickAdd" : "quickAddWired", {
            name: nodeName,
            port: portLabel,
          })}
          // A button on the card, not a click on the node: xyflow would select it.
          onClick={(event) => event.stopPropagation()}
          className={cn(
            "nodrag nopan bg-background text-muted-foreground hover:text-foreground hover:border-foreground/40 focus-visible:ring-ring flex size-5 items-center justify-center rounded-full border shadow-sm transition-opacity outline-none focus-visible:ring-2",
            next.length === 0 || open
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
        {only !== undefined && (
          <div
            role="radiogroup"
            aria-label={t("quickAddPlacement")}
            className="flex gap-1 border-b p-2"
          >
            <PlacementChoice checked={!branch} onSelect={() => setBranch(false)}>
              {t("quickAddInsertBefore", { name: only.name })}
            </PlacementChoice>
            <PlacementChoice checked={branch} onSelect={() => setBranch(true)}>
              {t("quickAddBranch")}
            </PlacementChoice>
          </div>
        )}
        {next.length > 1 && (
          <p className="text-muted-foreground border-b p-2 text-xs">
            {t("quickAddBranchBeside", { count: next.length })}
          </p>
        )}
        <NodePicker
          offered={offered}
          onPick={(definition, config) => {
            onPick(definition, config, only !== undefined && !branch ? only.edgeId : undefined);
            setOpen(false);
            setBranch(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

function PlacementChoice({
  checked,
  onSelect,
  children,
}: {
  checked: boolean;
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      onClick={onSelect}
      className={cn(
        "focus-visible:ring-ring min-w-0 flex-1 truncate rounded-md border px-2 py-1 text-xs outline-none focus-visible:ring-2",
        checked
          ? "border-primary bg-primary/10 text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
