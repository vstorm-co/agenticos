"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Boxes,
  BookOpen,
  Cpu,
  Library,
  Maximize,
  MessageSquare,
  Plug,
  Wallet,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

/** One box on the map. `items` empty means "nothing configured", said out loud. */
export interface MapNode {
  key: string;
  title: string;
  icon: LucideIcon;
  items: string[];
  /** What to say when there is nothing - the reason to open the map at all. */
  empty: string;
  /** Which side of the agent it hangs off. */
  side: "in" | "out";
}

interface AgentMapProps {
  agentName: string;
  instructions: string;
  nodes: MapNode[];
}

/** A cubic curve between two points, flat at both ends so it meets the box square-on. */
function curve(from: { x: number; y: number }, to: { x: number; y: number }): string {
  const bend = Math.max(32, Math.abs(to.x - from.x) / 2);
  return `M ${from.x} ${from.y} C ${from.x + bend} ${from.y}, ${to.x - bend} ${to.y}, ${to.x} ${to.y}`;
}

/**
 * The agent as a diagram: what reaches it, and what it reaches for.
 *
 * The Builder is a column of forms, which is the right shape for editing one
 * thing and the wrong shape for the question people actually ask before they
 * publish - *what is this agent, in total?* Six collapsed sections do not answer
 * that; a picture does, and an empty box on it is the fastest way to notice the
 * skill nobody attached.
 *
 * Read-only on purpose. Making the map editable would mean a second way to
 * change every field, drifting from the forms that own them.
 *
 * The edges are measured rather than drawn at fixed coordinates: the boxes are
 * laid out by the browser (their height depends on how many things they list),
 * so a hand-placed curve would land in the middle of a box the moment somebody
 * attached a fourth skill.
 */
/** How far the wheel and the buttons may take the scale, either way. */
const MIN_SCALE = 0.4;
const MAX_SCALE = 2.5;

export function AgentMap({ agentName, instructions, nodes }: AgentMapProps) {
  const viewport = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const hub = useRef<HTMLDivElement>(null);
  const boxes = useRef(new Map<string, HTMLDivElement>());
  const [edges, setEdges] = useState<string[]>([]);

  // Pan and zoom as one transform on the content. The edges are measured in
  // the content's own coordinates, so the same transform carries them along
  // and nothing has to be re-measured while somebody drags.
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const viewRef = useRef(view);
  viewRef.current = view;
  const drag = useRef<{ pointerId: number; startX: number; startY: number } | null>(null);

  const measure = useCallback(() => {
    const root = container.current;
    const centre = hub.current;
    /* v8 ignore next -- React has attached both refs before any effect runs */
    if (!root || !centre) return;

    // Rects are in screen space, which the transform has already scaled; the
    // paths render inside the transformed content, so divide back to local.
    const scale = viewRef.current.scale;
    const origin = root.getBoundingClientRect();
    const hubBox = centre.getBoundingClientRect();
    const paths: string[] = [];

    for (const node of nodes) {
      const element = boxes.current.get(node.key);
      /* v8 ignore next -- every node renders a box and registers it by key */
      if (!element) continue;
      const box = element.getBoundingClientRect();
      const anchor = {
        x: ((node.side === "in" ? box.right : box.left) - origin.left) / scale,
        y: (box.top + box.height / 2 - origin.top) / scale,
      };
      const hubSide = {
        x: ((node.side === "in" ? hubBox.left : hubBox.right) - origin.left) / scale,
        y: (hubBox.top + hubBox.height / 2 - origin.top) / scale,
      };
      paths.push(node.side === "in" ? curve(anchor, hubSide) : curve(hubSide, anchor));
    }

    setEdges(paths);
  }, [nodes]);

  useLayoutEffect(measure, [measure]);

  useEffect(() => {
    const root = container.current;
    /* v8 ignore next -- as above: the ref is set before this effect */
    if (!root) return;
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    for (const element of boxes.current.values()) observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  /** Zoom keeping the given viewport point still - the cursor, or the centre. */
  const zoomAt = useCallback((point: { x: number; y: number }, factor: number) => {
    setView((current) => {
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, current.scale * factor));
      const ratio = scale / current.scale;
      return {
        scale,
        x: point.x - (point.x - current.x) * ratio,
        y: point.y - (point.y - current.y) * ratio,
      };
    });
  }, []);

  const zoomFromCentre = (factor: number) => {
    const box = viewport.current?.getBoundingClientRect();
    if (box) zoomAt({ x: box.width / 2, y: box.height / 2 }, factor);
  };

  // The wheel listener is attached by hand: React registers `onWheel` as
  // passive, and a passive listener cannot stop the dialog behind the map from
  // scrolling while somebody zooms.
  useEffect(() => {
    const element = viewport.current;
    /* v8 ignore next -- as above: the ref is set before this effect */
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const box = element.getBoundingClientRect();
      zoomAt(
        { x: event.clientX - box.left, y: event.clientY - box.top },
        event.deltaY < 0 ? 1.15 : 1 / 1.15,
      );
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const inputs = nodes.filter((node) => node.side === "in");
  const outputs = nodes.filter((node) => node.side === "out");

  return (
    <div className="relative">
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Zoom in"
          onClick={() => zoomFromCentre(1.25)}
        >
          <ZoomIn className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Zoom out"
          onClick={() => zoomFromCentre(1 / 1.25)}
        >
          <ZoomOut className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Reset view"
          onClick={() => setView({ x: 0, y: 0, scale: 1 })}
        >
          <Maximize className="h-4 w-4" />
        </Button>
      </div>

      <div
        ref={viewport}
        className="h-[65vh] cursor-grab touch-none overflow-hidden rounded-lg border select-none active:cursor-grabbing"
        onPointerDown={(event) => {
          drag.current = {
            pointerId: event.pointerId,
            startX: event.clientX - view.x,
            startY: event.clientY - view.y,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const active = drag.current;
          if (!active || active.pointerId !== event.pointerId) return;
          setView((current) => ({
            ...current,
            x: event.clientX - active.startX,
            y: event.clientY - active.startY,
          }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <div
          ref={container}
          className="relative origin-top-left p-4"
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
        >
          <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
            {edges.map((path, index) => (
              <path
                key={index}
                d={path}
                fill="none"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                // The dashes travel from source to sink - into the agent on the
                // left, out of it on the right. Reduced-motion strips it
                // globally in globals.css.
                className="map-flow stroke-brand/50"
              />
            ))}
          </svg>

          <div className="relative grid items-center gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_minmax(0,1fr)]">
            <div className="space-y-4">
              {inputs.map((node) => (
                <NodeBox
                  key={node.key}
                  node={node}
                  ref={(element) => {
                    if (element) boxes.current.set(node.key, element);
                    else boxes.current.delete(node.key);
                  }}
                />
              ))}
            </div>

            <div
              ref={hub}
              className="border-brand/40 bg-card rounded-xl border-2 p-4 shadow-sm"
              role="group"
              aria-label={`${agentName}, the agent`}
            >
              <p className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
                Agent
              </p>
              <p className="mt-1 text-base font-semibold">{agentName}</p>
              <p className="text-muted-foreground mt-4 text-[11px] font-medium tracking-wide uppercase">
                Instructions
              </p>
              {instructions.trim() ? (
                <p className="text-muted-foreground mt-1 line-clamp-6 text-sm whitespace-pre-wrap">
                  {instructions}
                </p>
              ) : (
                <p className="text-muted-foreground mt-1 text-sm italic">No instructions written</p>
              )}
            </div>

            <div className="space-y-4">
              {outputs.map((node) => (
                <NodeBox
                  key={node.key}
                  node={node}
                  ref={(element) => {
                    if (element) boxes.current.set(node.key, element);
                    else boxes.current.delete(node.key);
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function NodeBox({ node, ref }: { node: MapNode; ref: (element: HTMLDivElement | null) => void }) {
  const Icon = node.icon;
  const isEmpty = node.items.length === 0;

  return (
    <div
      ref={ref}
      role="group"
      aria-label={node.title}
      className={cn(
        "bg-card rounded-xl border p-3",
        // An empty box is the finding, not a formatting problem: dashed says
        // "nothing here" at a glance, across five boxes at once.
        isEmpty && "border-dashed",
      )}
    >
      <p className="text-muted-foreground flex items-center gap-1.5 text-[11px] font-medium tracking-wide uppercase">
        <Icon className="h-3.5 w-3.5" />
        {node.title}
        {!isEmpty && <span className="ml-auto normal-case">{node.items.length}</span>}
      </p>
      {isEmpty ? (
        <p className="text-muted-foreground mt-2 text-sm">{node.empty}</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {node.items.map((item) => (
            <li key={item} className="truncate text-sm">
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The icons the Builder passes in, kept here so the map owns its own vocabulary. */
export const MAP_ICONS = {
  channels: MessageSquare,
  model: Cpu,
  capabilities: Boxes,
  mcp: Plug,
  skills: Library,
  knowledge: BookOpen,
  budget: Wallet,
} as const;
