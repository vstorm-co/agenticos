import { HEIGHT, PETS, WIDTH, draw, frames } from "./pet-sprites.js";
import {
  HAPPY_MS,
  HOP_MS,
  NO_STROKE,
  SAY_MS,
  WAVE_MS,
  clampToArea,
  frameIndex,
  gazeToward,
  logicalArea,
  nextBehaviour,
  stroke,
  strollStep,
} from "./pet-engine.js";
import { pickLine } from "./pet-lines.js";

const { invoke } = window.__TAURI__.core;
const { getCurrentWindow, currentMonitor, cursorPosition, LogicalPosition } = window.__TAURI__.window;
const { listen } = window.__TAURI__.event;

function report(message) {
  void invoke("page_error", { message: String(message) });
}
window.addEventListener("error", (event) => report(event.message));
window.addEventListener("unhandledrejection", (event) => report(event.reason));

const SCALE = 6;
const DRAG_THRESHOLD = 4;
const DOUBLE_CLICK_MS = 350;
const SAVE_DELAY_MS = 400;
const GAZE_POLL_MS = 250;
const QUIP_CHANCE = 0.15;

const win = getCurrentWindow();
const canvas = document.getElementById("pet");
const newChat = document.getElementById("new-chat");
const bubble = document.getElementById("bubble");
canvas.width = WIDTH * SCALE;
canvas.height = HEIGHT * SCALE;
const ctx = canvas.getContext("2d");
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let kind = "orbit";
let behaviour = { state: "idle", ms: 5000, dir: 1 };
let behaviourStart = performance.now();
let reaction = null;
let gaze = 0;
let pos = null;
let size = null;
let area = null;
let scale = 1;
let lastTick = performance.now();
let pressed = null;
let dragging = false;
let lastClickAt = 0;
let saveTimer = null;
let bubbleTimer = null;
let lastLine = null;
let stroking = NO_STROKE;

function current() {
  return reaction ?? behaviour;
}

function react(state, ms) {
  reaction = { state, ms, dir: 1, until: performance.now() + ms };
}

function say(line) {
  bubble.textContent = line;
  document.body.classList.add("talking");
  clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(() => document.body.classList.remove("talking"), SAY_MS);
}

function quip() {
  lastLine = pickLine(kind, Math.random, lastLine);
  say(lastLine);
}

function render(now) {
  const { state, dir } = current();
  const start = reaction ? reaction.until - reaction.ms : behaviourStart;
  const all = frames(kind, state, dir, gaze);
  draw(ctx, all[frameIndex(state, now - start, all.length)], PETS[kind].palette, SCALE);
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
    behaviour = nextBehaviour(Math.random, new Date().getHours());
    behaviourStart = now;
    if (Math.random() < QUIP_CHANCE) quip();
  }
  if (!reaction && behaviour.state === "stroll" && !pressed) void stroll(dt);
  render(now);
  requestAnimationFrame(tick);
}

/** The eyes follow the cursor while the pet is standing about; asleep or walking, they do not. */
async function watchCursor() {
  const { state } = current();
  if (!pos || !size || (state !== "idle" && state !== "wave")) {
    gaze = 0;
    return;
  }
  const cursor = await cursorPosition();
  gaze = gazeToward(cursor.x / scale, pos.x + size.width / 2);
}

/** Once the window has come to rest: re-measure - it may be on another monitor now - then save. */
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      await measure();
      if (pos) await invoke("save_pet_position", { x: pos.x, y: pos.y });
    } catch (e) {
      report(e);
    }
    if (dragging) {
      dragging = false;
      react("hop", HOP_MS);
    }
  }, SAVE_DELAY_MS);
}

async function measure() {
  scale = await win.scaleFactor();
  const outer = await win.outerPosition();
  const outerSize = await win.outerSize();
  const monitor = await currentMonitor();
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
  if (!pressed) {
    if (reaction) return;
    stroking = stroke(stroking, event.clientX, performance.now());
    if (stroking.pleased) {
      stroking = NO_STROKE;
      react("happy", HAPPY_MS);
    }
    return;
  }
  if (Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) < DRAG_THRESHOLD) return;
  pressed = null;
  dragging = true;
  void win.startDragging();
});

canvas.addEventListener("pointerup", () => {
  if (!pressed) return;
  pressed = null;
  const now = performance.now();
  if (now - lastClickAt < DOUBLE_CLICK_MS) {
    lastClickAt = 0;
    react("hop", HOP_MS);
    void invoke("show_console").catch(report);
    return;
  }
  lastClickAt = now;
  react("wave", WAVE_MS);
  quip();
});

canvas.addEventListener("pointercancel", () => {
  pressed = null;
});

canvas.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  void invoke("pet_menu").catch(report);
});

newChat.addEventListener("click", () => {
  react("hop", HOP_MS);
  void invoke("open_chat").catch(report);
});

async function start() {
  const settings = await invoke("pet_settings");
  kind = settings.kind;
  await listen("pet-kind", (event) => {
    kind = event.payload;
    quip();
    if (reduceMotion) render(performance.now());
  });
  await listen("pet-say", (event) => say(event.payload));
  await win.onMoved(async ({ payload }) => {
    pos = { x: payload.x / scale, y: payload.y / scale };
    scheduleSave();
  });
  await measure();
  if (reduceMotion) {
    behaviour = { state: "idle", ms: Infinity, dir: 1 };
    render(performance.now());
    return;
  }
  setInterval(() => void watchCursor().catch(report), GAZE_POLL_MS);
  requestAnimationFrame(tick);
}

start().catch(report);
