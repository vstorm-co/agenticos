import { VARIANTS, WIDTH, HEIGHT, frames, draw } from "./pet-sprites.js";
import { HOP_MS, WAVE_MS, clampToArea, frameIndex, logicalArea, nextBehaviour, strollStep } from "./pet-engine.js";

const { invoke } = window.__TAURI__.core;
const { getCurrentWindow, LogicalPosition } = window.__TAURI__.window;
const { listen } = window.__TAURI__.event;

const SCALE = 6;
const DRAG_THRESHOLD = 4;
const DOUBLE_CLICK_MS = 350;
const SAVE_DELAY_MS = 400;

const win = getCurrentWindow();
const canvas = document.getElementById("pet");
canvas.width = WIDTH * SCALE;
canvas.height = HEIGHT * SCALE;
const ctx = canvas.getContext("2d");
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let palette = VARIANTS.orbit;
let behaviour = { state: "idle", ms: 5000, dir: 1 };
let behaviourStart = performance.now();
let reaction = null;
let pos = null;
let size = null;
let area = null;
let lastTick = performance.now();
let pressed = null;
let lastClickAt = 0;
let saveTimer = null;

function current() {
  return reaction ?? behaviour;
}

function react(state, ms) {
  reaction = { state, ms, dir: 1, until: performance.now() + ms };
}

function render(now) {
  const { state, dir } = current();
  const start = reaction ? reaction.until - reaction.ms : behaviourStart;
  const all = frames(state, dir);
  draw(ctx, all[frameIndex(state, now - start, all.length)], palette, SCALE);
}

async function stroll(dtMs) {
  if (!pos || !size || !area) return;
  const step = strollStep(pos.x, behaviour.dir, dtMs, area.x, area.x + area.width - size.width);
  behaviour.dir = step.dir;
  pos = { x: step.x, y: pos.y };
  await win.setPosition(new LogicalPosition(pos.x, pos.y));
}

function tick(now) {
  const dt = now - lastTick;
  lastTick = now;
  if (reaction && now >= reaction.until) reaction = null;
  if (!reaction && now - behaviourStart >= behaviour.ms) {
    behaviour = nextBehaviour(Math.random);
    behaviourStart = now;
  }
  if (!reaction && behaviour.state === "stroll" && !pressed) void stroll(dt);
  render(now);
  requestAnimationFrame(tick);
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    if (pos) void invoke("save_pet_position", { x: pos.x, y: pos.y }).catch(console.error);
  }, SAVE_DELAY_MS);
}

async function measure() {
  const scale = await win.scaleFactor();
  const outer = await win.outerPosition();
  const outerSize = await win.outerSize();
  const monitor = await win.currentMonitor();
  pos = { x: outer.x / scale, y: outer.y / scale };
  size = { width: outerSize.width / scale, height: outerSize.height / scale };
  if (monitor) {
    area = logicalArea(monitor);
    const inside = clampToArea(pos, size, area);
    if (inside.x !== pos.x || inside.y !== pos.y) {
      pos = inside;
      await win.setPosition(new LogicalPosition(pos.x, pos.y));
    }
  }
}

canvas.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  pressed = { x: event.clientX, y: event.clientY };
});

canvas.addEventListener("pointermove", (event) => {
  if (!pressed) return;
  if (Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) < DRAG_THRESHOLD) return;
  pressed = null;
  void win.startDragging();
});

canvas.addEventListener("pointerup", () => {
  if (!pressed) return;
  pressed = null;
  const now = performance.now();
  if (now - lastClickAt < DOUBLE_CLICK_MS) {
    lastClickAt = 0;
    react("hop", HOP_MS);
    void invoke("show_console").catch(console.error);
    return;
  }
  lastClickAt = now;
  react("wave", WAVE_MS);
});

canvas.addEventListener("pointercancel", () => {
  pressed = null;
});

async function start() {
  const settings = await invoke("pet_settings");
  palette = VARIANTS[settings.variant];
  await listen("pet-variant", (event) => {
    palette = VARIANTS[event.payload];
    if (reduceMotion) render(performance.now());
  });
  await win.onMoved(async ({ payload }) => {
    const scale = await win.scaleFactor();
    pos = { x: payload.x / scale, y: payload.y / scale };
    scheduleSave();
  });
  await measure();
  if (reduceMotion) {
    behaviour = { state: "idle", ms: Infinity, dir: 1 };
    draw(ctx, frames("idle")[0], palette, SCALE);
    return;
  }
  requestAnimationFrame(tick);
}

start().catch(console.error);
