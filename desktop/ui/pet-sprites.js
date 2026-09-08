/**
 * The pet's pixel art: a 16 × 24 grid of palette keys, composed frame by frame.
 *
 * One body, drawn once, and a handful of parts placed on it - eyes, feet, an arm,
 * the antenna, a Z. A frame is a placement of those parts, so an animation is a few
 * lines of positions rather than a sprite sheet nobody can edit by hand.
 */

export const WIDTH = 16;
export const HEIGHT = 24;

/** Palette keys → colours. `B` body, `D` outline, `L` highlight, `A` antenna, `W`/`K` eye. */
export const VARIANTS = {
  orbit: { B: "#5a8cda", D: "#2f4f86", L: "#9dbcf0", A: "#f2c14e", W: "#ffffff", K: "#1a1f2e" },
  mint: { B: "#5cc9a5", D: "#2e6e5a", L: "#a8e8d2", A: "#f28c5c", W: "#ffffff", K: "#1a2e26" },
  ember: { B: "#e0845a", D: "#7d3a22", L: "#f4bfa3", A: "#5a8cda", W: "#ffffff", K: "#2e1a14" },
};

export const FPS = { idle: 3, look: 2, stroll: 6, doze: 1, wave: 5, hop: 8 };

const BASE_Y = 8;

const BODY = [
  ".....DDDDDD.....",
  "...DDBBBBBBDD...",
  "..DBBLLBBBBBBD..",
  ".DBBLBBBBBBBBBD.",
  ".DBBBBBBBBBBBBD.",
  "DBBBBBBBBBBBBBBD",
  "DBBBBBBBBBBBBBBD",
  "DBBBBBBBBBBBBBBD",
  "DBBBBBBBBBBBBBBD",
  ".DBBBBBBBBBBBBD.",
  ".DBBBBBBBBBBBBD.",
  "..DBBBBBBBBBBD..",
  "...DDBBBBBBDD...",
  ".....DDDDDD.....",
];
const ANTENNA_DOT = ["AAA", "AAA"];
const STALK = ["D", "D"];
const FOOT = ["DDD", "DDD"];
const Z = ["DDD", ".D.", "DDD"];
const EYES = {
  open: ["WK", "KK", "KK"],
  closed: ["..", "KK", ".."],
};
const ARM = {
  up: { x: 13, y: 3, rows: [".DD", "DBD", "DD."] },
  down: { x: 13, y: 5, rows: ["DD.", "DBD", ".DD"] },
};
const FEET = { stand: [4, 9], a: [3, 10], b: [5, 8] };

/** Paint layers onto a blank grid, later layers over earlier; `.` is transparent. */
export function compose(layers) {
  const grid = Array.from({ length: HEIGHT }, () => Array.from({ length: WIDTH }, () => "."));
  for (const { x, y, rows } of layers) {
    rows.forEach((row, dy) => {
      [...row].forEach((key, dx) => {
        const gx = x + dx;
        const gy = y + dy;
        if (key === "." || gx < 0 || gy < 0 || gx >= WIDTH || gy >= HEIGHT) return;
        grid[gy][gx] = key;
      });
    });
  }
  return grid.map((row) => row.join(""));
}

function frame({ bob = 0, lift = 0, eyes = "open", gaze = 0, feet = "stand", arm = null, z = null }) {
  const body = BASE_Y + bob - lift;
  const layers = [];
  if (z !== null) layers.push({ x: 12 + z, y: BASE_Y - 4 + z - lift, rows: Z });
  layers.push({ x: 6, y: BASE_Y - 4 - lift, rows: ANTENNA_DOT });
  layers.push({ x: 7, y: body - 2, rows: STALK });
  layers.push({ x: 0, y: body, rows: BODY });
  layers.push({ x: 4 + gaze, y: body + 4, rows: EYES[eyes] }, { x: 10 + gaze, y: body + 4, rows: EYES[eyes] });
  if (arm) layers.push({ x: ARM[arm].x, y: BASE_Y + ARM[arm].y - lift, rows: ARM[arm].rows });
  const [left, right] = FEET[feet];
  layers.push({ x: left, y: BASE_Y + 14 - lift, rows: FOOT }, { x: right, y: BASE_Y + 14 - lift, rows: FOOT });
  return compose(layers);
}

const ANIMATIONS = {
  idle: () => [{ bob: 0 }, { bob: 1 }, { bob: 1 }, { bob: 0 }, { eyes: "closed" }, { bob: 0 }],
  look: () => [{ gaze: -1 }, { gaze: -1 }, { gaze: -1, bob: 1 }, { gaze: 1 }, { gaze: 1, bob: 1 }, { gaze: 1 }],
  stroll: (dir) => [
    { feet: "a", gaze: dir },
    { feet: "stand", bob: 1, gaze: dir },
    { feet: "b", gaze: dir },
    { feet: "stand", bob: 1, gaze: dir },
  ],
  doze: () => [
    { eyes: "closed", bob: 1, z: 0 },
    { eyes: "closed", bob: 1, z: 1 },
  ],
  wave: () => [{ arm: "up" }, { arm: "down" }],
  hop: () => [{ lift: 1 }, { lift: 3 }, { lift: 4 }, { lift: 3 }, { lift: 1 }, { bob: 1 }],
};

const cache = new Map();

/** The composed frames of one animation; `dir` is -1 or 1 and only `stroll` reads it. */
export function frames(state, dir = 1) {
  const key = `${state}:${dir}`;
  if (!cache.has(key)) cache.set(key, ANIMATIONS[state](dir).map(frame));
  return cache.get(key);
}

export function draw(ctx, grid, palette, scale) {
  ctx.clearRect(0, 0, WIDTH * scale, HEIGHT * scale);
  grid.forEach((row, y) => {
    [...row].forEach((key, x) => {
      if (key === ".") return;
      ctx.fillStyle = palette[key];
      ctx.fillRect(x * scale, y * scale, scale, scale);
    });
  });
}
