"use client";

import { Command } from "cmdk";
import { BrandIcon } from "@/components/icons/brand-icon";
import { ArrowLeft, ChevronRight, Plus, RefreshCw, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { appToolLabel, serverGroupId } from "@/components/workflows/apps";
import { NodeTile } from "@/components/workflows/node-tile";
import { sectionSwatchClass } from "@/components/workflows/node-visuals";
import { writeNodeDragData } from "@/components/workflows/palette/drag";
import {
  useAppConnections,
  useRefreshWorkflowMcpTools,
} from "@/components/workflows/use-app-connections";
import { WorkflowConnectionsDialog } from "@/components/workflows/pickers/workflow-connections-dialog";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";
import { cn } from "@/lib/utils";

import {
  type AppAction,
  type PickerGroup,
  matchesAction,
  matchesSearch,
  pickerSections,
} from "./groups";

interface NodePickerProps {
  /** The steps that may be added here, already narrowed to the scope in view. */
  offered: readonly NodeDefinition[];
  /**
   * `config` is set when an app's action was picked: the `mcp.call` it adds is
   * then already pointed at that connection and tool.
   */
  onPick: (definition: NodeDefinition, config?: Record<string, unknown>) => void;
  /** Whether a row may also be dragged onto the canvas, to place the step there. */
  draggable?: boolean;
}

const GROUP_HEADING =
  "[&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:uppercase";

type TileFor =
  { kind: "step" | "operation"; item: NodeDefinition } | { kind: "group"; category: string };

type FoundRow =
  | { kind: "step"; item: NodeDefinition; name: string; group: PickerGroup }
  | { kind: "action"; action: AppAction; name: string; group: PickerGroup };

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
  const [openGroup, setOpen] = useState<PickerGroup | null>(null);
  const coloured = useWorkflowNodeStyleStore((state) => state.style) === "colour";

  const label = (category: string) =>
    sections.flatMap((section) => section.groups).find((group) => group.category === category)?.app
      ?.app.name ?? (t.has(`category.${category}`) ? t(`category.${category}`) : category);
  const hint = (category: string) =>
    t.has(`categoryHint.${category}`) ? t(`categoryHint.${category}`) : null;

  const { connections, canConnect, unavailable, servers = [] } = useAppConnections(query);
  const sections = pickerSections(offered, {
    connections,
    canConnect,
    unavailable,
    catalog: servers,
  });
  const open =
    openGroup === null
      ? null
      : (sections
          .flatMap((section) => section.groups)
          .find((group) => group.category === openGroup.category) ?? openGroup);
  const searching = query.trim() !== "";
  const actionLabel = (action: AppAction) => appToolLabel(action.app, action.tool, t);
  // A few dozen steps: filtered on every keystroke, no memo to keep in step.
  const found: FoundRow[] = searching
    ? sections.flatMap((section) =>
        section.groups.flatMap((group): FoundRow[] => [
          // An app's trigger is listed under Triggers already: not twice.
          ...(group.app === undefined
            ? group.items
                .filter((item) => matchesSearch(item, query, label(group.category)))
                .map((item): FoundRow => ({ kind: "step", item, name: item.name, group }))
            : []),
          ...(group.app?.actions ?? [])
            .filter((action) =>
              matchesAction(action, query, actionLabel(action), label(group.category)),
            )
            .map((action): FoundRow => ({
              kind: "action",
              action,
              name: actionLabel(action),
              group,
            })),
        ]),
      )
    : [];
  // A step whose name says it comes before one that only mentions it.
  const named = (row: FoundRow) => row.name.toLowerCase().includes(query.trim().toLowerCase());
  found.sort((a, b) => Number(named(b)) - Number(named(a)));

  const actionRow = (group: PickerGroup, action: AppAction, groupLabel?: string) => {
    const name = actionLabel(action);
    return (
      <Command.Item
        key={action.key}
        value={`action:${action.key}`}
        onSelect={() =>
          onPick(action.definition, { connection_id: action.connectionId, tool: action.tool })
        }
        className="aria-selected:bg-accent flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2"
      >
        <Tile kind="group" category={group.category} />
        <span className="min-w-0 flex-1">
          <span className="block text-sm break-words">{name}</span>
          {/* Nothing hidden: the tool's own name, as the connection lists it, on its own line. */}
          <span className="text-muted-foreground block font-mono text-xs break-all">
            {action.tool}
          </span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-0.5">
          <span className="text-muted-foreground border-border rounded border px-1 text-[10px] font-medium tracking-wide">
            {t("appMcpBadge")}
          </span>
          <span className="text-muted-foreground max-w-32 text-right text-xs break-words">
            {groupLabel ?? action.connectionName}
          </span>
        </span>
      </Command.Item>
    );
  };

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
          found.length === 0 &&
          !sections.some((section) =>
            section.groups.some(
              (group) =>
                group.app !== undefined &&
                label(group.category).toLowerCase().includes(query.toLowerCase()),
            ),
          ) ? (
            <p className="text-muted-foreground px-3 py-8 text-center text-sm">
              {t("paletteNoMatches")}
            </p>
          ) : (
            <>
              {sections
                .flatMap((section) => section.groups)
                .filter(
                  (group) =>
                    group.app !== undefined &&
                    group.app.actions.length === 0 &&
                    label(group.category).toLowerCase().includes(query.toLowerCase()),
                )
                .map((group) => (
                  <Command.Item
                    key={group.category}
                    value={`discover:${group.category}`}
                    onSelect={() => {
                      setOpen(group);
                      setQuery("");
                    }}
                    className="aria-selected:bg-accent flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-sm"
                  >
                    <Tile kind="group" category={group.category} />
                    {label(group.category)}
                    <ChevronRight className="ml-auto size-4" />
                  </Command.Item>
                ))}
              {found.map((row) =>
                row.kind === "step"
                  ? stepRow(row.item, "step", label(row.group.category))
                  : actionRow(
                      row.group,
                      row.action,
                      `${label(row.group.category)} · ${row.action.connectionName}`,
                    ),
              )}
            </>
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
                  {open.app !== undefined && (
                    <span className="mt-0.5 block text-xs font-normal tracking-normal normal-case">
                      {open.app.app.name ?? t(`appServerFull.${serverGroupId(open.app.app)}`)}
                    </span>
                  )}
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
              {open.app?.actions.map((action) => actionRow(open, action))}
              {open.app?.untested.map(({ id, name }) => (
                <UntestedConnection key={id} id={id} name={name} canRefresh={canConnect} />
              ))}
              {open.app?.connectKey != null && (
                <ConnectRow group={open} catalogKey={open.app.connectKey} />
              )}
              {open.app?.needsPermission === true && (
                <p className="text-muted-foreground px-2 py-1.5 text-xs">
                  {t("appNeedsPermission", { app: label(open.category) })}
                </p>
              )}
              {open.app !== undefined && (
                <p className="text-muted-foreground px-2 pt-1.5 text-xs">{t("appOrgOnly")}</p>
              )}
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
                if (group.items.length === 1 && group.app === undefined) {
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
                    {group.app?.app.brand !== undefined ? (
                      <BrandIcon name={group.app.app.brand} className="size-7 shrink-0 p-1" />
                    ) : (
                      <Tile kind="group" category={group.category} />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{label(group.category)}</span>
                      {hint(group.category) !== null && (
                        <span className="text-muted-foreground block truncate text-xs">
                          {hint(group.category)}
                        </span>
                      )}
                    </span>
                    <span className="text-muted-foreground text-xs tabular-nums">
                      {group.items.length + (group.app?.actions.length ?? 0)}
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

/** The way to get an app's actions when no connection provides them: opens that catalog entry. */
function ConnectRow({ group, catalogKey }: { group: PickerGroup; catalogKey: string }) {
  const t = useTranslations("workflows");
  const [connecting, setConnecting] = useState(false);
  return (
    <>
      <Command.Item
        value={`connect:${catalogKey}`}
        onSelect={() => setConnecting(true)}
        className="aria-selected:bg-accent text-muted-foreground flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-xs"
      >
        <Plus aria-hidden="true" className="size-4 shrink-0" />
        {t("appConnect", { server: group.app?.app.name ?? t(`appServer.${group.category}`) })}
      </Command.Item>
      {connecting && (
        <WorkflowConnectionsDialog open catalogKey={catalogKey} onOpenChange={setConnecting} />
      )}
    </>
  );
}

function UntestedConnection({
  id,
  name,
  canRefresh,
}: {
  id: string;
  name: string;
  canRefresh: boolean;
}) {
  const t = useTranslations("workflows");
  const refresh = useRefreshWorkflowMcpTools();
  return (
    <div className="space-y-1 px-2 py-1.5 text-xs">
      <p className="text-muted-foreground">{t("appUntested", { connection: name })}</p>
      {canRefresh && (
        <Command.Item
          value={`refresh:${id}`}
          disabled={refresh.isPending}
          onSelect={() => refresh.mutate(id)}
          className="aria-selected:bg-accent flex cursor-pointer items-center gap-2 rounded-lg p-2"
        >
          <RefreshCw
            aria-hidden="true"
            className={cn("size-3.5", refresh.isPending && "animate-spin")}
          />
          {t("pickerMcpRefresh")}
        </Command.Item>
      )}
      {refresh.isError && (
        <p role="alert" className="text-destructive">
          {t("pickerMcpTestFailed")}
        </p>
      )}
    </div>
  );
}
