/** What the pet does when nobody is touching it, and the arithmetic of moving it. Pure. */

import { FPS } from "./pet-sprites.js";

export const WAVE_MS = 1600;
export const HOP_MS = 750;
export const STROLL_SPEED = 28;

export function frameIndex(state, elapsedMs, frameCount) {
  return Math.floor(elapsedMs / (1000 / FPS[state])) % frameCount;
}

/**
 * The next ambient behaviour, once the current one has run its course.
 *
 * Mostly idle, so the pet reads as company rather than as a distraction; a stroll
 * or a doze often enough to be noticed. `random` is injected so a test can pin it.
 */
export function nextBehaviour(random) {
  const roll = random();
  if (roll < 0.55) return { state: "idle", ms: 4000 + random() * 6000, dir: 1 };
  if (roll < 0.75) return { state: "look", ms: 2000 + random() * 2000, dir: 1 };
  if (roll < 0.9) return { state: "stroll", ms: 2500 + random() * 3000, dir: random() < 0.5 ? -1 : 1 };
  return { state: "doze", ms: 8000 + random() * 10000, dir: 1 };
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
