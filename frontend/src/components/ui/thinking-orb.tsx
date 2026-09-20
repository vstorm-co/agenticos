"use client";

import { ThinkingOrb as Orb, type OrbState } from "thinking-orbs";

import { cn } from "@/lib/utils";

export type { OrbState };

export interface ThinkingOrbProps {
  /** Which animation to show - what the work looks like, not what it is called. */
  state: OrbState;
  /**
   * Tuned size in CSS pixels. Two ship, and they are separate designs rather
   * than a scale factor: 20 for a line of text, 64 for an avatar.
   */
  size?: 20 | 64;
  className?: string;
}

/**
 * A dotted orb that says something is still happening.
 *
 * One canvas per orb, drawn client-side, resolving dark or light from the
 * `data-theme` attribute this application already sets on `<html>`. It replaces
 * a pulsing glyph where a run is in flight: a spinner says "busy", and an orb
 * that scans, braids or wires itself says which kind of busy - which is the
 * difference between a reader waiting and a reader following along.
 */
export function ThinkingOrb({ state, size = 64, className }: ThinkingOrbProps) {
  return <Orb state={state} size={size} className={cn("shrink-0", className)} aria-hidden />;
}
