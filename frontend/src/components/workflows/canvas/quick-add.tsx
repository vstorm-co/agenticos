"use client";

import { Command } from "cmdk";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { nodeVisual } from "@/components/workflows/node-visuals";
import { isAddableInScope } from "@/components/workflows/palette/scope";
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
 * The "+" beside a node's output: a searchable menu of the steps that can come
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
        className="w-72 p-0"
        align="start"
        side="right"
        onClick={(event) => event.stopPropagation()}
        // Focus goes to the step just added, not back to a "+" that has done its job.
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        {/* A plain substring match: cmdk's default scores scattered letters, so
            "notif" would rank "Download a file" alongside "Notify members". */}
        <Command
          filter={(value, search) => (value.toLowerCase().includes(search.toLowerCase()) ? 1 : 0)}
        >
          <div className="border-border border-b px-3 py-2">
            <Command.Input
              placeholder={t("quickAddSearch")}
              className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
            />
          </div>
          <Command.List className="max-h-72 overflow-y-auto p-1">
            <Command.Empty className="text-muted-foreground px-3 py-6 text-center text-sm">
              {t("paletteNoMatches")}
            </Command.Empty>
            {offered.map((definition) => {
              const visual = nodeVisual(definition.id, definition.category);
              const Icon = visual.icon;
              return (
                <Command.Item
                  key={`${definition.id}@${definition.version}`}
                  value={`${definition.name} ${definition.description} ${definition.category}`}
                  onSelect={() => {
                    onPick(definition);
                    setOpen(false);
                  }}
                  className="aria-selected:bg-accent flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-2"
                >
                  <span
                    className={cn(
                      "flex size-7 shrink-0 items-center justify-center rounded-md",
                      visual.tileClass,
                    )}
                  >
                    <Icon aria-hidden="true" className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{definition.name}</span>
                    <span className="text-muted-foreground block truncate text-xs">
                      {definition.description}
                    </span>
                  </span>
                </Command.Item>
              );
            })}
          </Command.List>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
