"use client";

import { ArrowUpRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { DelegationMode } from "@/types/agents";
import { useTranslations } from "next-intl";

import type { MapSide } from "./agent-map-view";

/** One capability box on the map. `items` empty means "nothing configured", said out loud. */
export interface MapNode {
  key: string;
  title: string;
  icon: LucideIcon;
  items: string[];
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

interface CapabilityNodeProps {
  node: MapNode;
  focused: boolean;
  dimmed: boolean;
  onFocus: () => void;
  registerRef: (element: HTMLElement | null) => void;
}

/**
 * A capability, as a box that lists what is attached - or names what is not.
 *
 * A button rather than a card because it is one now: clicking or pressing Enter
 * focuses it, which lights its edge and opens the detail panel. An empty box is
 * still the finding it always was, dashed so it reads as "nothing here" across
 * five boxes at once.
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
        "bg-card block w-full rounded-xl border p-3 text-left transition",
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
    </button>
  );
}

interface DelegateNodeProps {
  delegate: MapDelegate;
  icon: LucideIcon;
  focused: boolean;
  dimmed: boolean;
  onFocus: () => void;
  registerRef: (element: HTMLElement | null) => void;
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
        <span className="text-muted-foreground flex items-center gap-1.5 text-[11px] tracking-wide uppercase">
          <span>{t(KIND_LABEL[delegate.kind])}</span>
          {delegate.mode && (
            <span className="bg-muted rounded px-1 py-0.5 normal-case">
              {t(MODE_LABEL[delegate.mode])}
            </span>
          )}
        </span>
      </span>
      {delegate.href && <ArrowUpRight className="text-muted-foreground h-3.5 w-3.5 shrink-0" />}
    </button>
  );
}
