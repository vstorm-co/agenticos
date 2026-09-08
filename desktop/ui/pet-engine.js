/** What the pet does when nobody is touching it, and the arithmetic of moving it. Pure. */

import { FPS } from "./pet-sprites.js";

export const WAVE_MS = 1600;
export const HOP_MS = 750;
export const HAPPY_MS = 2000;
export const SAY_MS = 2400;
export const STROLL_SPEED = 28;
export const GAZE_DEADZONE = 40;
export const STROKES_TO_PLEASE = 4;
export const STROKE_WINDOW_MS = 1500;

export function frameIndex(state, elapsedMs, frameCount) {
  return Math.floor(elapsedMs / (1000 / FPS[state])) % frameCount;
}

export function isNight(hour) {
  return hour >= 22 || hour < 7;
}

/**
 * The next ambient behaviour, once the current one has run its course.
 *
 * Mostly idle, so the pet reads as company rather than as a distraction; a stroll
 * or a doze often enough to be noticed, and at night the doze takes the stroll's
 * share. `random` is injected so a test can pin it; `hour` is the local one.
 */
export function nextBehaviour(random, hour = 12) {
  const roll = random();
  if (roll < 0.55) return { state: "idle", ms: 4000 + random() * 6000, dir: 1 };
  if (roll < 0.75) return { state: "look", ms: 2000 + random() * 2000, dir: 1 };
  if (roll < 0.9 && !isNight(hour)) {
    return { state: "stroll", ms: 2500 + random() * 3000, dir: random() < 0.5 ? -1 : 1 };
  }
  return { state: "doze", ms: 8000 + random() * 10000, dir: 1 };
}

/** Where the eyes point at a cursor: -1 left, 1 right, 0 when it is about in front. */
export function gazeToward(cursorX, centreX) {
  const offset = cursorX - centreX;
  if (Math.abs(offset) < GAZE_DEADZONE) return 0;
  return offset < 0 ? -1 : 1;
}

export const NO_STROKE = { x: 0, dir: 0, reversals: 0, since: 0, pleased: false };

/**
 * Stroking: the cursor going back and forth over the pet, unpressed.
 *
 * One step of the tracker. Reversals count only inside the window opened by the
 * first of them, so a cursor merely passing through never pleases anybody; four
 * inside a second and a half do.
 */
export function stroke(tracker, x, now) {
  const dir = Math.sign(x - tracker.x);
  if (dir === 0) return { ...tracker, x };
  const reversed = tracker.dir !== 0 && dir !== tracker.dir;
  const expired = now - tracker.since > STROKE_WINDOW_MS;
  const reversals = expired ? Number(reversed) : tracker.reversals + Number(reversed);
  const since = reversed && (expired || tracker.reversals === 0) ? now : tracker.since;
  return { x, dir, reversals, since, pleased: reversals >= STROKES_TO_PLEASE };
}

/** One tick of a stroll along x, turning round at either edge instead of leaving the screen. */
export function strollStep(x, dir, dtMs, min, max) {
  const next = x + (dir * STROLL_SPEED * dtMs) / 1000;
  if (next < min) return { x: min, dir: 1 };
  if (next > max) return { x: max, dir: -1 };
  return { x: next, dir };
}

/** A monitor's usable rectangle in logical pixels, from the physical one Tauri reports. */
export function logicalArea(monitor) {
  const area = monitor.workArea ?? { position: monitor.position, size: monitor.size };
  const s = monitor.scaleFactor;
  return {
    x: area.position.x / s,
    y: area.position.y / s,
    width: area.size.width / s,
    height: area.size.height / s,
  };
}

export function clampToArea(pos, size, area) {
  const x = Math.min(Math.max(pos.x, area.x), area.x + area.width - size.width);
  const y = Math.min(Math.max(pos.y, area.y), area.y + area.height - size.height);
  return { x, y };
}
