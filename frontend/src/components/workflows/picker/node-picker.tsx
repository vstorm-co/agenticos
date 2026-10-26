"use client";

import { Command } from "cmdk";
import { ArrowLeft, ChevronRight, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { NodeTile } from "@/components/workflows/node-tile";
import { sectionSwatchClass } from "@/components/workflows/node-visuals";
import { writeNodeDragData } from "@/components/workflows/palette/drag";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";
import { cn } from "@/lib/utils";

import { type PickerGroup, matchesSearch, pickerSections } from "./groups";

interface NodePickerProps {
  /** The steps that may be added here, already narrowed to the scope in view. */
  offered: readonly NodeDefinition[];
  onPick: (definition: NodeDefinition) => void;
  /** Whether a row may also be dragged onto the canvas, to place the step there. */
  draggable?: boolean;
}

const GROUP_HEADING =
  "[&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:uppercase";

type TileFor =
  { kind: "step" | "operation"; item: NodeDefinition } | { kind: "group"; category: string };

function Tile(which: TileFor) {
  const shape = { className: "size-7 rounded-lg", iconClassName: "size-3.5" };
  return which.kind === "group" ? (
    <NodeTile kind="group" category={which.category} {...shape} />
  ) : (
    <NodeTile
      kind={which.kind}
      definitionId={which.item.id}
      category={which.item.category}
      {...shape}
    />
  );
}

/**
 * Choosing the next step: sections of groups - Agents, Tables, Slack - and each
 * group's steps one level down, or every step matching a search at once.
 *
 * The one list every way of adding a step opens - the canvas's "Add step", the
 * "+" beside an output - so a step is found in the same place however it is
 * added. Arrow keys move through it and Enter picks; Backspace in an empty
 * search, or the back row, leaves a group.
 */
export function NodePicker({ offered, onPick, draggable = false }: NodePickerProps) {
  const t = useTranslations("workflows");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<PickerGroup | null>(null);
  const coloured = useWorkflowNodeStyleStore((state) => state.style) === "colour";

  const label = (category: string) =>
    t.has(`category.${category}`) ? t(`category.${category}`) : category;
  const hint = (category: string) =>
    t.has(`categoryHint.${category}`) ? t(`categoryHint.${category}`) : null;

  const sections = useMemo(() => pickerSections(offered), [offered]);
  const searching = query.trim() !== "";
  // A few dozen steps: filtered on every keystroke, no memo to keep in step.
  const found = searching
    ? sections.flatMap((section) =>
        section.groups.flatMap((group) =>
          group.items
            .filter((item) => matchesSearch(item, query, label(group.category)))
            .map((item) => ({ item, group })),
        ),
      )
    : [];
  // A step whose name says it comes before one that only mentions it.
  const named = (item: NodeDefinition) =>
    item.name.toLowerCase().includes(query.trim().toLowerCase());
  found.sort((a, b) => Number(named(b.item)) - Number(named(a.item)));

  const stepRow = (item: NodeDefinition, kind: "step" | "operation", groupLabel?: string) => (
    <Command.Item
      key={`${item.id}@${item.version}`}
      value={`${item.id}@${item.version}`}
      onSelect={() => onPick(item)}
      draggable={draggable}
      onDragStart={(event) => writeNodeDragData(event.dataTransfer, item)}
      className="aria-selected:bg-accent flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2"
    >
      <Tile kind={kind} item={item} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm">{item.name}</span>
        <span className="text-muted-foreground line-clamp-2 text-xs">{item.description}</span>
      </span>
      {groupLabel !== undefined && (
        <span className="text-muted-foreground shrink-0 text-xs">{groupLabel}</span>
      )}
    </Command.Item>
  );

  return (
    <Command
      shouldFilter={false}
      loop
      className="flex max-h-[min(34rem,70vh)] flex-col"
      onKeyDown={(event) => {
        if (event.key === "Backspace" && query === "" && open !== null) {
          event.preventDefault();
          setOpen(null);
        }
      }}
    >
      <div className="border-border flex items-center gap-2 border-b px-3 py-2.5">
        <Search aria-hidden="true" className="text-muted-foreground size-4 shrink-0" />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder={t("pickerSearch")}
          aria-label={t("pickerSearch")}
          className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
        />
      </div>
      <Command.List className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {searching ? (
          found.length === 0 ? (
            <p className="text-muted-foreground px-3 py-8 text-center text-sm">
              {t("paletteNoMatches")}
            </p>
          ) : (
            found.map(({ item, group }) => stepRow(item, "step", label(group.category)))
          )
        ) : open !== null ? (
          <>
            <Command.Item
              value="__back__"
              onSelect={() => setOpen(null)}
              className="aria-selected:bg-accent text-muted-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-medium"
            >
              <ArrowLeft aria-hidden="true" className="size-3.5" />
              {t("pickerBack")}
            </Command.Item>
            {/* A heading, not a row: styled as one so it is never mistaken for a step. */}
            <Command.Group
              heading={
                <>
                  {label(open.category)}
                  {hint(open.category) !== null && (
                    <span className="mt-0.5 block text-xs font-normal tracking-normal normal-case">
                      {hint(open.category)}
                    </span>
                  )}
                </>
              }
              className={cn(GROUP_HEADING, "border-border mt-1 border-t pt-1")}
            >
              {open.items.map((item) => stepRow(item, "operation"))}
            </Command.Group>
          </>
        ) : (
          sections.map((section) => (
            <Command.Group
              key={section.id}
              heading={
                <span className="flex items-center gap-1.5">
                  {coloured && sectionSwatchClass(section.id) !== undefined && (
                    <span
                      aria-hidden="true"
                      className={cn("size-2 rounded-full", sectionSwatchClass(section.id))}
                    />
                  )}
                  {t(`pickerSection.${section.id}`)}
                </span>
              }
              className={cn(GROUP_HEADING, "mb-1")}
            >
              {section.groups.map((group) => {
                // A group of one step is that step: a click adds it at once.
                if (group.items.length === 1) {
                  const only = group.items[0] as NodeDefinition;
                  return stepRow(only, "step");
                }
                return (
                  <Command.Item
                    key={group.category}
                    value={`group:${group.category}`}
                    onSelect={() => {
                      setOpen(group);
                      setQuery("");
                    }}
                    className="aria-selected:bg-accent flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2"
                  >
                    <Tile kind="group" category={group.category} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{label(group.category)}</span>
                      {hint(group.category) !== null && (
                        <span className="text-muted-foreground block truncate text-xs">
                          {hint(group.category)}
                        </span>
                      )}
                    </span>
                    <span className="text-muted-foreground text-xs tabular-nums">
                      {group.items.length}
                    </span>
                    <ChevronRight aria-hidden="true" className="text-muted-foreground size-4" />
                  </Command.Item>
                );
              })}
            </Command.Group>
          ))
        )}
      </Command.List>
    </Command>
  );
}
