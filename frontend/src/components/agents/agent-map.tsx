"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Boxes, BookOpen, Cpu, Library, MessageSquare, Plug, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";

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
export function AgentMap({ agentName, instructions, nodes }: AgentMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const hub = useRef<HTMLDivElement>(null);
  const boxes = useRef(new Map<string, HTMLDivElement>());
  const [edges, setEdges] = useState<string[]>([]);

  const measure = useCallback(() => {
    const root = container.current;
    const centre = hub.current;
    if (!root || !centre) return;

    const origin = root.getBoundingClientRect();
    const hubBox = centre.getBoundingClientRect();
    const paths: string[] = [];

    for (const node of nodes) {
      const element = boxes.current.get(node.key);
      if (!element) continue;
      const box = element.getBoundingClientRect();
      const anchor = {
        x: (node.side === "in" ? box.right : box.left) - origin.left,
        y: box.top + box.height / 2 - origin.top,
      };
      const hubSide = {
        x: (node.side === "in" ? hubBox.left : hubBox.right) - origin.left,
        y: hubBox.top + hubBox.height / 2 - origin.top,
      };
      paths.push(node.side === "in" ? curve(anchor, hubSide) : curve(hubSide, anchor));
    }

    setEdges(paths);
  }, [nodes]);

  useLayoutEffect(measure, [measure]);

  useEffect(() => {
    const root = container.current;
    if (!root) return;
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    for (const element of boxes.current.values()) observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  const inputs = nodes.filter((node) => node.side === "in");
  const outputs = nodes.filter((node) => node.side === "out");

  return (
    <div ref={container} className="relative">
      <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
        {edges.map((path, index) => (
          <path
            key={index}
            d={path}
            fill="none"
            strokeWidth={1.5}
            strokeDasharray="4 4"
            className="stroke-border"
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
