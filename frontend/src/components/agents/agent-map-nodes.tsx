"use client";

import { ArrowUpRight } from "lucide-react";
import type { ComponentType } from "react";

import type { LucideIcon } from "lucide-react";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { cn } from "@/lib/utils";
import type { DelegationMode } from "@/types/agents";
import { useTranslations } from "next-intl";

import type { MapSide } from "./agent-map-view";

/**
 * One thing inside a group on the map - a surface, a capability, a server.
 *
 * A node used to hold a list of strings, and a list of strings is a paragraph:
 * five surfaces and four capabilities read as two blocks of text rather than as
 * nine things. Each one is drawn as its own tile now, with the mark its own kind
 * of thing wears everywhere else in the console.
 */
export interface MapItem {
  key: string;
  label: string;
  /**
   * The mark for this kind of thing, where one exists.
   *
   * Structural rather than `LucideIcon`, because a surface's mark may be a brand
   * glyph: `brandMark` builds a component from compiled-in path data, and one
   * table serving both is the point - a surface must not wear one face here and
   * another in run history.
   */
  icon?: ComponentType<{ className?: string }>;
  /**
   * An MCP connection's icon name, drawn as that server's own brand mark.
   *
   * Its own field rather than a `LucideIcon`, because `McpServerIcon` resolves
   * three sources in order - a compiled-in brand glyph, a mark the deployment
   * ships, then a monogram - and a caller picking one of them would be a fourth
   * answer to what a server looks like.
   */
  mcp?: { icon: string | null; name: string };
  /** Present but not answering - a paused channel binding. */
  muted?: boolean;
}

/** One capability box on the map. `items` empty means "nothing configured", said out loud. */
export interface MapNode {
  key: string;
  title: string;
  icon: LucideIcon;
  items: MapItem[];
  /** What to say when there is nothing - the reason to open the map at all. */
  empty: string;
  /** Which side of the agent it hangs off. */
  side: MapSide;
}

/**
 * One subagent on the map: another agent this one reaches for, not a tool.
 *
 * A delegate is a published agent pinned to a version and so has a page of its
 * own; a specialist is defined inline and has none. The map draws both, and the
 * distinction is the whole reason they are a different kind of node.
 */
export interface MapDelegate {
  key: string;
  name: string;
  kind: "delegate" | "specialist";
  /** The override the parent's model follows for this one, or null to follow policy. */
  mode: DelegationMode | null;
  /** The delegate's own page, when it is a published agent this caller can reach. */
  href?: string;
  /** Why a run would not follow this pin - absent means it would. */
  problem?: "restricted" | "unpinned" | "cycle" | "archived";
  /** The delegate has published past the pinned version. */
  stale?: boolean;
  /** Has a roster of its own that a run from this map's root can never reach. */
  truncated?: boolean;
  /** What it delegates to in turn - the recursive half of the tree (#276). */
  children?: MapDelegate[];
}

/** Catalog keys, translated at the point of use - a module table cannot call `t`. */
export const KIND_LABEL: Record<MapDelegate["kind"], string> = {
  delegate: "mapDelegate",
  specialist: "mapSpecialist",
};
export const MODE_LABEL: Record<DelegationMode, string> = {
  sync: "modeSync",
  async: "modeAsync",
  auto: "modeAuto",
};
export const PROBLEM_LABEL: Record<NonNullable<MapDelegate["problem"]>, string> = {
  restricted: "mapNoAccessBadge",
  unpinned: "pinGone",
  cycle: "mapCycleBadge",
  archived: "mapArchivedBadge",
};
export const PROBLEM_DETAIL: Record<NonNullable<MapDelegate["problem"]>, string> = {
  restricted: "delegateUnreachableDetail",
  unpinned: "delegatePinGoneDetail",
  cycle: "mapCycleDetail",
  archived: "mapArchivedDetail",
};

interface CapabilityNodeProps {
  node: MapNode;
  focused: boolean;
  dimmed: boolean;
  onFocus: () => void;
  registerRef: (element: HTMLElement | null) => void;
}

/**
 * A group, as a box holding one tile per thing inside it - or naming what is not
 * there.
 *
 * A button rather than a card because it is one now: clicking or pressing Enter
 * focuses it, which lights its edge and opens the detail panel. An empty box is
 * still the finding it always was, dashed so it reads as "nothing here" across
 * five boxes at once.
 *
 * The tiles are what makes the map a map. A list of names is a paragraph, and a
 * paragraph of nine lines is read as one shape - so a reader looking for "is
 * Slack on here" was scanning text. Each thing is a tile with the mark it wears
 * everywhere else in the console, so the answer is a glance. They arrive in
 * sequence rather than all at once: the stagger is what makes a group of eight
 * read as eight things rather than one block appearing.
 */
export function CapabilityNode({
  node,
  focused,
  dimmed,
  onFocus,
  registerRef,
}: CapabilityNodeProps) {
  const Icon = node.icon;
  const isEmpty = node.items.length === 0;

  return (
    <button
      type="button"
      ref={registerRef}
      aria-label={node.title}
      aria-pressed={focused}
      onClick={(event) => {
        // Stop the click reaching the viewport, whose own handler reads a click
        // on the canvas as "clear the focus".
        event.stopPropagation();
        onFocus();
      }}
      className={cn(
        "bg-card block w-full rounded-xl border p-3.5 text-left transition",
        "focus-visible:ring-brand focus-visible:ring-2 focus-visible:outline-none",
        isEmpty && "border-dashed",
        focused && "ring-brand ring-2",
        dimmed && "opacity-40",
      )}
    >
      <p className="text-muted-foreground flex items-center gap-1.5 text-[11px] font-medium tracking-wide uppercase">
        <Icon className="h-3.5 w-3.5" />
        {node.title}
        {!isEmpty && <span className="ml-auto normal-case">{node.items.length}</span>}
      </p>
      {isEmpty ? (
        <p className="text-muted-foreground mt-2.5 text-sm">{node.empty}</p>
      ) : (
        <ul className="mt-2.5 flex flex-wrap gap-1.5">
          {node.items.map((item, index) => (
            <li
              key={item.key}
              className={cn(
                "map-tile bg-muted/50 border-border/60 flex max-w-full items-center gap-1.5",
                "rounded-lg border px-2 py-1 text-xs",
                item.muted && "opacity-55",
              )}
              // Sequenced rather than simultaneous, and capped: past a dozen the
              // wait before the last tile is longer than the glance it is for.
              style={{ animationDelay: `${Math.min(index, 12) * 25}ms` }}
            >
              <MapItemIcon item={item} />
              {/* Wrapped rather than truncated: the map is read at a glance, and
                  a model called "OpenRouter · anthr…" answers the one question
                  the tile exists for with an ellipsis. Tiles are short enough
                  that growing one costs a line. */}
              <span className="min-w-0 break-words">{item.label}</span>
            </li>
          ))}
        </ul>
      )}
    </button>
  );
}

/** The mark for one tile: a server's own, a kind's, or none. */
function MapItemIcon({ item }: { item: MapItem }) {
  if (item.mcp) {
    return <McpServerIcon icon={item.mcp.icon} name={item.mcp.name} className="h-3.5 w-3.5" />;
  }
  if (item.icon === undefined) return null;
  const Icon = item.icon;
  return <Icon className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />;
}

interface DelegateNodeProps {
  delegate: MapDelegate;
  icon: LucideIcon;
  focused: boolean;
  dimmed: boolean;
  onFocus: () => void;
  /** Only the first level measures an edge to the hub; deeper nodes hang off
   * their parent with a drawn connector instead. */
  registerRef?: (element: HTMLElement | null) => void;
}

/**
 * A subagent, shaped like a chip rather than a list - because it is an agent, not
 * a tool, and the map should not read it as one.
 *
 * The arrow marks the ones you can walk to: a published delegate has a page, and
 * the panel this opens links to it. A specialist has none, so it carries no arrow
 * and the panel says why.
 */
export function DelegateNode({
  delegate,
  icon: Icon,
  focused,
  dimmed,
  onFocus,
  registerRef,
}: DelegateNodeProps) {
  const t = useTranslations("agents");

  return (
    <button
      type="button"
      ref={registerRef}
      aria-label={delegate.name}
      aria-pressed={focused}
      onClick={(event) => {
        event.stopPropagation();
        onFocus();
      }}
      className={cn(
        "bg-card flex w-full items-center gap-2.5 rounded-full border py-1.5 pr-3 pl-1.5 text-left transition",
        "focus-visible:ring-brand focus-visible:ring-2 focus-visible:outline-none",
        focused && "ring-brand ring-2",
        dimmed && "opacity-40",
      )}
    >
      <span className="bg-brand/10 text-brand flex h-7 w-7 shrink-0 items-center justify-center rounded-full">
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{delegate.name}</span>
        <span className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-[11px] tracking-wide uppercase">
          <span>{t(KIND_LABEL[delegate.kind])}</span>
          {delegate.mode && (
            <span className="bg-muted rounded px-1 py-0.5 normal-case">
              {t(MODE_LABEL[delegate.mode])}
            </span>
          )}
          {delegate.problem && (
            <span className="bg-destructive/10 text-destructive rounded px-1 py-0.5 normal-case">
              {t(PROBLEM_LABEL[delegate.problem])}
            </span>
          )}
          {delegate.stale && (
            <span className="bg-muted rounded px-1 py-0.5 normal-case">{t("mapPinBehind")}</span>
          )}
          {delegate.truncated && (
            <span className="bg-muted rounded px-1 py-0.5 normal-case">{t("mapDepthCap")}</span>
          )}
        </span>
      </span>
      {delegate.href && <ArrowUpRight className="text-muted-foreground h-3.5 w-3.5 shrink-0" />}
    </button>
  );
}

interface DelegateBranchProps {
  nodes: MapDelegate[];
  icons: Record<MapDelegate["kind"], LucideIcon>;
  focused: string | null;
  onFocus: (key: string) => void;
}

/**
 * The recursive half of the delegation tree: a delegate's own delegates,
 * indented under it with a drawn connector instead of a measured edge.
 *
 * The hub's edges are measured because its nodes sit anywhere on a grid; a
 * subtree is a list whose parent is always directly above, so a border is the
 * honest connector and it cannot break however deep or wide the tree gets -
 * which is what an arbitrary-depth graph needs from a layout (#276).
 */
export function DelegateBranch({ nodes, icons, focused, onFocus }: DelegateBranchProps) {
  return (
    <ul className="border-brand/30 mt-1 ml-4 space-y-1 border-l pl-3">
      {nodes.map((node) => (
        <li key={node.key}>
          <DelegateNode
            delegate={node}
            icon={icons[node.kind]}
            focused={focused === node.key}
            dimmed={focused !== null && focused !== node.key}
            onFocus={() => onFocus(node.key)}
          />
          {node.children && node.children.length > 0 && (
            <DelegateBranch
              nodes={node.children}
              icons={icons}
              focused={focused}
              onFocus={onFocus}
            />
          )}
        </li>
      ))}
    </ul>
  );
}
