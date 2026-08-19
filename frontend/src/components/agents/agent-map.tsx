"use client";

import { useMemo, type ComponentType } from "react";
import {
  BookOpen,
  Bot,
  Boxes,
  Cpu,
  Gauge,
  GitBranch,
  Library,
  Maximize,
  MessageSquare,
  Network,
  Plug,
  Radio,
  UserCog,
  Wallet,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  CapabilityNode,
  DelegateBranch,
  DelegateNode,
  type MapDelegate,
  type MapNode,
} from "./agent-map-nodes";
import { MapDetail } from "./agent-map-detail";
import { useMapView, type EdgeInput } from "./agent-map-view";
import { useFocusedNode } from "./use-focused-node";
import { surfaceIconComponent } from "@/components/runs/surface-icon";
import { Button } from "@/components/ui";
import { STEP_ICONS } from "@/lib/step-icons";
import { toolEntry } from "@/lib/tool-catalog";
import { cn } from "@/lib/utils";
import type { CapabilityCatalogEntry } from "@/types/agents";
import { useTranslations } from "next-intl";

export type { MapNode, MapDelegate };

interface AgentMapProps {
  agentName: string;
  instructions: string;
  nodes: MapNode[];
  /** Published delegates and inline specialists, drawn as their own kind of node.
   * A delegate's `children` is the recursive half - its own tree, drawn inline. */
  delegates?: MapDelegate[];
  /** One line under the delegation heading when the tree is partial - the fetch
   * failed, or the server stopped at its node bound. Null when it is whole. */
  delegationNotice?: string | null;
}

/** The icon each subagent kind wears - an agent, never a tool. */
const DELEGATE_ICON: Record<MapDelegate["kind"], LucideIcon> = {
  delegate: Bot,
  specialist: UserCog,
};

/**
 * A stable default for the `delegates` prop.
 *
 * `delegates = []` in the signature is a fresh array every render, which walks
 * through the `edgeInputs` memo into a new `measure`, whose layout effect calls
 * `setEdges` - and that re-render mints another `[]`. One shared constant breaks
 * the loop.
 */
const NO_DELEGATES: MapDelegate[] = [];

/**
 * The agent as a diagram: what reaches it, and what it reaches for.
 *
 * The Builder is a column of forms, which is the right shape for editing one
 * thing and the wrong shape for the question people actually ask before they
 * publish - *what is this agent, in total?* A picture answers that, and an empty
 * box on it is the fastest way to notice the skill nobody attached.
 *
 * Read-only on purpose. Making the map editable would mean a second way to change
 * every field, drifting from the forms that own them - so clicking a node focuses
 * it rather than editing it. The one place the map leaves itself is a published
 * delegate's own page: focusing a delegate offers the link, and the map becomes a
 * way to walk the delegation tree one hop at a time.
 *
 * The edges are measured rather than drawn at fixed coordinates - see
 * `useMapView`, which owns that half along with pan and zoom.
 */
export function AgentMap({
  agentName,
  instructions,
  nodes,
  delegates = NO_DELEGATES,
  delegationNotice = null,
}: AgentMapProps) {
  const t = useTranslations("agents");
  const { focused, focus, clear } = useFocusedNode();

  // Every delegate at every depth, for the detail panel: focus is one flat
  // namespace however deep the node sits, because the panel is one panel.
  const flatDelegates = useMemo(() => {
    const flatten = (list: MapDelegate[]): MapDelegate[] =>
      list.flatMap((entry) => [entry, ...(entry.children ? flatten(entry.children) : [])]);
    return flatten(delegates);
  }, [delegates]);

  const edgeInputs = useMemo<EdgeInput[]>(
    () => [
      ...nodes.map((node) => ({ key: node.key, side: node.side })),
      // A delegate is another agent, and a tree grows downward.
      ...delegates.map((delegate) => ({ key: delegate.key, side: "bottom" as const })),
    ],
    [nodes, delegates],
  );

  const {
    viewport,
    container,
    hub,
    registerBox,
    edges,
    view,
    zoomFromCentre,
    resetView,
    panHandlers,
  } = useMapView(edgeInputs);

  // Four directions, each answering its own question (#518): left is what
  // reaches the agent, top is what it runs as, right is what it reaches for,
  // bottom is what it hands work to.
  const lefts = nodes.filter((node) => node.side === "left");
  const rights = nodes.filter((node) => node.side === "right");
  const tops = nodes.filter((node) => node.side === "top");
  const bottoms = nodes.filter((node) => node.side === "bottom");

  // The focused item, for the detail panel. Exactly one of these matches.
  const focusedNode = nodes.find((node) => node.key === focused);
  const focusedDelegate = flatDelegates.find((delegate) => delegate.key === focused);

  return (
    <div className="relative">
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={t("zoom")}
          onClick={() => zoomFromCentre(1.25)}
        >
          <ZoomIn className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={t("zoomOut")}
          onClick={() => zoomFromCentre(1 / 1.25)}
        >
          <ZoomOut className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={t("resetView")}
          onClick={resetView}
        >
          <Maximize className="h-4 w-4" />
        </Button>
      </div>

      {/* The pan/zoom canvas. A click that lands here rather than on a node is
          how a person says "never mind", so it clears the focus - nodes stop
          their own clicks from reaching it. The keyboard has its own way out
          (Escape, handled in useFocusedNode) and the panel its own close
          button, so the click handler is a pointer affordance the a11y rules
          cannot see the keyboard twin of. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div
        ref={viewport}
        className="h-[65vh] cursor-grab touch-none overflow-hidden rounded-lg border select-none active:cursor-grabbing"
        onClick={clear}
        {...panHandlers}
      >
        <div
          ref={container}
          className="relative origin-top-left p-8"
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
        >
          <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
            {edges.map(({ key, path }) => (
              <path
                key={key}
                d={path}
                fill="none"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                // The dashes travel from source to sink - into the agent on the
                // left, out of it on the right. Reduced-motion strips it globally
                // in globals.css. A focused node lights its own edge and dims the
                // rest, so the eye follows the one thing the panel describes.
                className={cn(
                  "map-flow",
                  focused === key ? "stroke-brand" : "stroke-brand/50",
                  focused !== null && focused !== key && "opacity-20",
                )}
              />
            ))}
          </svg>

          {/* Wider gutters than a form's, because the gaps are where the edges
              run: at 24px a dashed line crossed a box before it reached one, and
              the picture read as boxes with lines behind them rather than as
              boxes joined by lines. */}
          <div className="relative grid items-center gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)_minmax(0,1fr)]">
            {/* Row above the hub: what the agent runs as. The flanking cells
                keep the grid's auto-placement honest on large screens. */}
            {tops.length > 0 && (
              <>
                <div className="hidden lg:block" />
                <div className="grid gap-5 sm:grid-cols-2">
                  {tops.map((node) => (
                    <CapabilityNode
                      key={node.key}
                      node={node}
                      focused={focused === node.key}
                      dimmed={focused !== null && focused !== node.key}
                      onFocus={() => focus(node.key)}
                      registerRef={registerBox(node.key)}
                    />
                  ))}
                </div>
                <div className="hidden lg:block" />
              </>
            )}

            <div className="space-y-5">
              {lefts.map((node) => (
                <CapabilityNode
                  key={node.key}
                  node={node}
                  focused={focused === node.key}
                  dimmed={focused !== null && focused !== node.key}
                  onFocus={() => focus(node.key)}
                  registerRef={registerBox(node.key)}
                />
              ))}
            </div>

            <div
              ref={hub}
              className={cn(
                "border-brand/40 bg-card rounded-xl border-2 p-4 shadow-sm transition",
                focused !== null && "opacity-40",
              )}
              role="group"
              aria-label={t("theAgentItself", { name: agentName })}
            >
              <p className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
                {t("agent")}
              </p>
              <p className="mt-1 text-base font-semibold">{agentName}</p>
              <p className="text-muted-foreground mt-4 text-[11px] font-medium tracking-wide uppercase">
                {t("instructions")}
              </p>
              {instructions.trim() ? (
                <p className="text-muted-foreground mt-1 line-clamp-6 text-sm whitespace-pre-wrap">
                  {instructions}
                </p>
              ) : (
                <p className="text-muted-foreground mt-1 text-sm italic">
                  {t("noInstructionsWritten")}
                </p>
              )}
            </div>

            <div className="space-y-5">
              {rights.map((node) => (
                <CapabilityNode
                  key={node.key}
                  node={node}
                  focused={focused === node.key}
                  dimmed={focused !== null && focused !== node.key}
                  onFocus={() => focus(node.key)}
                  registerRef={registerBox(node.key)}
                />
              ))}
            </div>

            {/* Row below the hub: what the agent hands work to. A delegate is
                another agent, so it is a node of its own down here rather than
                a line of text in a box - and a tree grows downward. Rendered
                only when there is anything: an empty delegation row on every
                agent that never delegates would be noise, not a finding. */}
            {(bottoms.length > 0 || delegates.length > 0) && (
              <>
                <div className="hidden lg:block" />
                <div className="space-y-5">
                  {bottoms.map((node) => (
                    <CapabilityNode
                      key={node.key}
                      node={node}
                      focused={focused === node.key}
                      dimmed={focused !== null && focused !== node.key}
                      onFocus={() => focus(node.key)}
                      registerRef={registerBox(node.key)}
                    />
                  ))}
                  {delegates.length > 0 && (
                    <section className="space-y-2" aria-label={t("delegation")}>
                      {delegationNotice && (
                        <p className="text-muted-foreground text-xs">{delegationNotice}</p>
                      )}
                      <div className="grid gap-2 sm:grid-cols-2">
                        {delegates.map((delegate) => (
                          <div key={delegate.key} className="min-w-0">
                            <DelegateNode
                              delegate={delegate}
                              icon={DELEGATE_ICON[delegate.kind]}
                              focused={focused === delegate.key}
                              dimmed={focused !== null && focused !== delegate.key}
                              onFocus={() => focus(delegate.key)}
                              registerRef={registerBox(delegate.key)}
                            />
                            {delegate.children && delegate.children.length > 0 && (
                              <DelegateBranch
                                nodes={delegate.children}
                                icons={DELEGATE_ICON}
                                focused={focused}
                                onFocus={focus}
                              />
                            )}
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                </div>
                <div className="hidden lg:block" />
              </>
            )}
          </div>
        </div>
      </div>

      {focusedNode && (
        <MapDetail
          title={focusedNode.title}
          icon={focusedNode.icon}
          node={focusedNode}
          onClose={clear}
        />
      )}
      {focusedDelegate && (
        <MapDetail
          title={focusedDelegate.name}
          icon={DELEGATE_ICON[focusedDelegate.kind]}
          delegate={focusedDelegate}
          onClose={clear}
        />
      )}
    </div>
  );
}

/** The icons the Builder passes in, kept here so the map owns its own vocabulary. */
export const MAP_ICONS = {
  surfaces: MessageSquare,
  model: Cpu,
  capabilities: Boxes,
  mcp: Plug,
  skills: Library,
  knowledge: BookOpen,
  budget: Wallet,
  delegation: Network,
} as const;

/**
 * Marks for the tiles *inside* a group, where the group's own icon would say
 * nothing - four identical network glyphs down the delegation box is a column of
 * decoration.
 *
 * Only what has no mark elsewhere. A surface's comes from `SurfaceIcon`, a
 * server's from `McpServerIcon`, and a capability's from the step-kind table the
 * chat reads: this is the short list of things that appear on the map and
 * nowhere else.
 */
export const MAP_ITEM_ICONS = {
  socket: Radio,
  mode: GitBranch,
  roster: UserCog,
  limit: Gauge,
} as const;

/**
 * The mark a surface wears, from the one table that owns surface marks.
 *
 * `SurfaceIcon` renders it directly everywhere else; the map needs the
 * *component* because a tile's icon is a prop rather than an element. Both read
 * the same table, so a surface cannot wear two faces here and in run history.
 */
export function surfaceMark(surface: string): ComponentType<{ className?: string }> | undefined {
  return surfaceIconComponent(surface);
}

/**
 * What a capability's tools do, as one mark.
 *
 * From the first tool the capability declares, because a capability is usually
 * about one kind of work - `knowledge` searches, `sandbox` runs a shell - and
 * the alternative is a second table naming a mark per capability id, which
 * drifts the day somebody adds one.
 */
export function capabilityMark(entry: CapabilityCatalogEntry | undefined): LucideIcon {
  const first = entry?.tools[0];
  const kind = first === undefined ? null : toolEntry(first.id)?.kind;
  return kind === undefined || kind === null ? MAP_ICONS.capabilities : STEP_ICONS[kind];
}
