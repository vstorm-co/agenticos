/**
 * The pets' pixel art: a 16 × 24 grid of palette keys, composed frame by frame.
 *
 * Each pet is one body and a description of where its parts go - eyes, feet, an
 * arm, whatever it wears on its head. A frame is a placement of those parts, so an
 * animation is a few lines of positions shared by every pet rather than a sprite
 * sheet per pet nobody can edit by hand.
 */

export const WIDTH = 16;
export const HEIGHT = 24;

export const FPS = { idle: 3, look: 2, stroll: 6, doze: 1, wave: 5, hop: 8 };

const BASE_Y = 8;

const FOOT = ["DDD", "DDD"];
const Z = ["DDD", ".D.", "DDD"];
const EYES = {
  open: ["WK", "KK", "KK"],
  closed: ["..", "KK", ".."],
};

/**
 * Palette keys → colours. `B` body, `D` outline, `L` highlight, `A` accent, `W`/`K` eye.
 *
 * `body` rows sit with their top at `top` (relative to the pet's baseline, which
 * is `BASE_Y`). Everything else is placed relative to that same baseline. `feet`
 * is `null` for a pet that floats.
 */
export const PETS = {
  orbit: {
    palette: { B: "#5a8cda", D: "#2f4f86", L: "#9dbcf0", A: "#f2c14e", W: "#ffffff", K: "#1a1f2e" },
    top: 0,
    body: [
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
    ],
    eyes: { x: [4, 10], y: 4 },
    feet: { y: 14, x: { stand: [4, 9], a: [3, 10], b: [5, 8] } },
    arm: {
      up: { x: 13, y: -1, rows: [".DD", "DBD", "DD."] },
      down: { x: 13, y: 1, rows: ["DD.", "DBD", ".DD"] },
    },
    crown: [
      { x: 7, y: -2, rows: ["D", "D"], rides: "body" },
      { x: 6, y: -4, rows: ["AAA", "AAA"], rides: "air" },
    ],
  },
  boxy: {
    palette: { B: "#6b7a90", D: "#2b323f", L: "#a3b1c6", A: "#5cc9a5", W: "#d9fff1", K: "#1a2e26" },
    top: 2,
    body: [
      "..DDDDDDDDDDDD..",
      "..DBLLBBBBBBBD..",
      "..DBLBBBBBBBBD..",
      "..DBBBBBBBBBBD..",
      "..DBBBBBBBBBBD..",
      "..DBBBBBBBBBBD..",
      "..DBBBBBBBBBBD..",
      "..DBBBBBBBBBBD..",
      "..DBBBBBBBBBBD..",
      "..DBBAAAAAABBD..",
      "..DBBBBBBBBBBD..",
      "..DDDDDDDDDDDD..",
    ],
    eyes: { x: [4, 10], y: 5 },
    feet: { y: 14, x: { stand: [3, 10], a: [2, 11], b: [4, 9] } },
    arm: {
      up: { x: 13, y: 0, rows: [".DD", "DBD", "DD."] },
      down: { x: 13, y: 3, rows: ["DD.", "DBD", ".DD"] },
    },
    crown: [
      { x: 7, y: 0, rows: ["D", "D"], rides: "body" },
      { x: 6, y: -2, rows: ["AAA", "AAA"], rides: "air" },
    ],
  },
  ghost: {
    palette: { B: "#a78bfa", D: "#5b3fa6", L: "#d6c8fd", A: "#f2c14e", W: "#ffffff", K: "#2a1d4d" },
    top: 1,
    body: [
      ".....DDDDDD.....",
      "...DDBBBBBBDD...",
      "..DBBLLBBBBBBD..",
      ".DBBLBBBBBBBBBD.",
      ".DBBBBBBBBBBBBD.",
      "DBBBBBBBBBBBBBBD",
      "DBBBBBBBBBBBBBBD",
      "DBBBBBBBBBBBBBBD",
      "DBBBBBBBBBBBBBBD",
      "DBBBBBBBBBBBBBBD",
      "DBBBBBBBBBBBBBBD",
      "DBBBBBBBBBBBBBBD",
      "DBBDBBBDDBBBDBBD",
      "DBD.DBD..DBD.DBD",
      ".D...D....D...D.",
    ],
    eyes: { x: [4, 10], y: 5 },
    feet: null,
    arm: {
      up: { x: 13, y: 0, rows: [".DD", "DBD", "DD."] },
      down: { x: 13, y: 2, rows: ["DD.", "DBD", ".DD"] },
    },
    crown: [],
  },
  amigo: {
    palette: {
      B: "#c8412b",
      D: "#4a2c17",
      L: "#f2c14e",
      A: "#d99a5b",
      R: "#8e1b1b",
      S: "#f1c27d",
      M: "#5b3a1e",
      G: "#2e8b57",
      W: "#ffffff",
      K: "#1a1f2e",
    },
    top: 0,
    body: [
      "DAAAAAAAAAAAAAAD",
      ".DRRRRRRRRRRRRD.",
      "....DSSSSSSD....",
      "....DSSSSSSD....",
      "....DSSSSSSD....",
      "....DSSSSSSD....",
      "...DMMMSSMMMD...",
      "...DBBBBBBBBD...",
      "..DBBGGGGGGBBD..",
      ".DBBBBBBBBBBBBD.",
      ".DBGGGGGGGGGGBD.",
      ".DBBBBBBBBBBBBD.",
      ".DBLLLLLLLLLLBD.",
      ".DDDDDDDDDDDDDD.",
    ],
    eyes: { x: [5, 9], y: 3 },
    feet: { y: 14, x: { stand: [4, 9], a: [3, 10], b: [5, 8] } },
    arm: {
      up: { x: 13, y: 6, rows: [".DD", "DSD", "BD."] },
      down: { x: 13, y: 9, rows: ["DD.", "DSD", ".DD"] },
    },
    crown: [{ x: 4, y: -3, rows: ["..DDDD..", ".DAAAAD.", "DAAAAAAD"], rides: "body" }],
  },
  sprout: {
    palette: { B: "#7bc96f", D: "#3d6b34", L: "#b9e6a8", A: "#4aa564", W: "#ffffff", K: "#1e2e1a" },
    top: 3,
    body: [
      ".......DD.......",
      "......DBBD......",
      ".....DBLBBD.....",
      "....DBBLBBBD....",
      "...DBBBBBBBBD...",
      "..DBBBBBBBBBBD..",
      ".DBBBBBBBBBBBBD.",
      ".DBBBBBBBBBBBBD.",
      ".DBBBBBBBBBBBBD.",
      "..DBBBBBBBBBBD..",
      "...DDBBBBBBDD...",
      ".....DDDDDD.....",
    ],
    eyes: { x: [4, 10], y: 6 },
    feet: { y: 14, x: { stand: [4, 9], a: [3, 10], b: [5, 8] } },
    arm: {
      up: { x: 13, y: 2, rows: [".DD", "DBD", "DD."] },
      down: { x: 13, y: 4, rows: ["DD.", "DBD", ".DD"] },
    },
    crown: [
      { x: 8, y: 1, rows: ["D", "D"], rides: "body" },
      { x: 9, y: -1, rows: [".AA", "AAA", "AA."], rides: "body" },
    ],
  },
};

export const KINDS = Object.keys(PETS);

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

function frame(pet, { bob = 0, lift = 0, eyes = "open", gaze = 0, feet = "stand", arm = null, z = null }) {
  const base = BASE_Y - lift;
  const body = base + pet.top + bob;
  const layers = [];
  if (z !== null) layers.push({ x: 12 + z, y: base - 4 + z, rows: Z });
  for (const piece of pet.crown) {
    const y = piece.rides === "air" ? base + piece.y : body - pet.top + piece.y;
    layers.push({ x: piece.x, y, rows: piece.rows });
  }
  layers.push({ x: 0, y: body, rows: pet.body });
  for (const x of pet.eyes.x) layers.push({ x: x + gaze, y: body + pet.eyes.y, rows: EYES[eyes] });
  if (arm) layers.push({ x: pet.arm[arm].x, y: body - pet.top + pet.arm[arm].y, rows: pet.arm[arm].rows });
  if (pet.feet) {
    for (const x of pet.feet.x[feet]) layers.push({ x, y: base + pet.feet.y, rows: FOOT });
  }
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

/** The composed frames of one pet's animation; `dir` is -1 or 1 and only `stroll` reads it. */
export function frames(kind, state, dir = 1) {
  const key = `${kind}:${state}:${dir}`;
  if (!cache.has(key)) cache.set(key, ANIMATIONS[state](dir).map((spec) => frame(PETS[kind], spec)));
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
