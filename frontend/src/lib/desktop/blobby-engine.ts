/**
 * What blobby does when nobody is touching it, what it says about the agents,
 * and the arithmetic of moving its window. Pure: every source of chance and time
 * is passed in, so a test can pin it.
 *
 * Ported from the pixel pets' `pet-engine.js`; the rules about when a stroke
 * counts and where it may walk are unchanged, the sprite frames are gone - the
 * face is a `blobatar`, and its expressions do what the frames did.
 */

import type { Chatter } from "@/lib/desktop/commands";

export const WAVE_MS = 1600;
export const HOP_MS = 750;
export const HAPPY_MS = 2000;
export const SAY_MS = 3200;
/** How long a bubble about the agents stays up; it comes back when the state changes. */
export const ACTIVITY_SAY_MS = 6000;
export const STROLL_SPEED = 28;
export const STROKES_TO_PLEASE = 4;
export const STROKE_WINDOW_MS = 1500;

export type Ambient = "idle" | "stroll" | "doze";
export type Reaction = "wave" | "hop" | "happy";
export type BlobbyState = Ambient | Reaction;

export interface Behaviour {
  state: Ambient;
  ms: number;
  /** Which way a stroll goes: -1 left, 1 right. */
  dir: -1 | 1;
}

export function isNight(hour: number): boolean {
  return hour >= 22 || hour < 7;
}

/**
 * The next ambient behaviour, once the current one has run its course.
 *
 * Mostly idle, so blobby reads as company rather than as a distraction; a stroll
 * or a doze often enough to be noticed. At night, or when it may not roam, the
 * doze takes the stroll's share. `random` is injected so a test can pin it;
 * `hour` is the local one.
 */
export function nextBehaviour(random: () => number, hour: number, roams: boolean): Behaviour {
  const roll = random();
  if (roll < 0.7) return { state: "idle", ms: 4000 + random() * 8000, dir: 1 };
  if (roll < 0.88 && roams && !isNight(hour)) {
    return { state: "stroll", ms: 2500 + random() * 3000, dir: random() < 0.5 ? -1 : 1 };
  }
  return { state: "doze", ms: 8000 + random() * 10000, dir: 1 };
}

/** How likely a quip is at each change of behaviour, by how chatty it was asked to be. */
export const QUIP_CHANCE: Record<Chatter, number> = { quiet: 0, normal: 0.15, chatty: 0.4 };

export interface StrokeTracker {
  x: number;
  dir: number;
  reversals: number;
  since: number;
  pleased: boolean;
}

export const NO_STROKE: StrokeTracker = { x: 0, dir: 0, reversals: 0, since: 0, pleased: false };

/**
 * Stroking: the cursor going back and forth over blobby, unpressed.
 *
 * One step of the tracker. Reversals count only inside the window opened by the
 * first of them, so a cursor merely passing through never pleases anybody; four
 * inside a second and a half do.
 */
export function stroke(tracker: StrokeTracker, x: number, now: number): StrokeTracker {
  const dir = Math.sign(x - tracker.x);
  if (dir === 0) return { ...tracker, x };
  const reversed = tracker.dir !== 0 && dir !== tracker.dir;
  const expired = now - tracker.since > STROKE_WINDOW_MS;
  const reversals = expired ? Number(reversed) : tracker.reversals + Number(reversed);
  const since = reversed && (expired || tracker.reversals === 0) ? now : tracker.since;
  return { x, dir, reversals, since, pleased: reversals >= STROKES_TO_PLEASE };
}

/** One tick of a stroll along x, turning round at either edge instead of leaving the screen. */
export function strollStep(
  x: number,
  dir: -1 | 1,
  dtMs: number,
  min: number,
  max: number,
): { x: number; dir: -1 | 1 } {
  const next = x + (dir * STROLL_SPEED * dtMs) / 1000;
  if (next < min) return { x: min, dir: 1 };
  if (next > max) return { x: max, dir: -1 };
  return { x: next, dir };
}

export interface Area {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Keep a window of `size` inside `area`, moving it the least. */
export function clampToArea(
  pos: { x: number; y: number },
  size: { width: number; height: number },
  area: Area,
): { x: number; y: number } {
  const x = Math.min(Math.max(pos.x, area.x), area.x + area.width - size.width);
  const y = Math.min(Math.max(pos.y, area.y), area.y + area.height - size.height);
  return { x, y };
}

/** What the agents are doing that blobby should mention, most urgent first. */
export type Activity =
  | { kind: "approvals"; count: number }
  | { kind: "unread"; count: number }
  | { kind: "running"; count: number }
  | { kind: "quiet" };

export function activityOf(signals: {
  approvals: number;
  unread: number;
  running: number;
}): Activity {
  if (signals.approvals > 0) return { kind: "approvals", count: signals.approvals };
  if (signals.unread > 0) return { kind: "unread", count: signals.unread };
  if (signals.running > 0) return { kind: "running", count: signals.running };
  return { kind: "quiet" };
}

/** Where a click on blobby's bubble about the agents goes. */
export function activityPath(activity: Activity): string | null {
  switch (activity.kind) {
    case "approvals":
      return "/runs?tab=approvals";
    case "running":
      return "/runs";
    case "unread":
    case "quiet":
      return null;
  }
}

/**
 * The face blobby wears: what it is doing, unless the agents need it to look
 * like something else. A waiting approval is surprise whatever it was doing - a
 * person glancing over should see it before reading anything.
 */
export type Expression = "idle" | "happy" | "love" | "sleepy" | "thinking" | "surprised";

export function expressionFor(state: BlobbyState, activity: Activity): Expression {
  if (state === "happy") return "love";
  if (state === "wave" || state === "hop") return "happy";
  if (activity.kind === "approvals") return "surprised";
  if (activity.kind === "running") return "thinking";
  if (state === "doze") return "sleepy";
  return "idle";
}
