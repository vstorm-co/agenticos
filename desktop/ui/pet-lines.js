/** What a pet says in its bubble. Short, because the bubble is the width of a pet. */

export const LINES = {
  orbit: ["Beep.", "Same version everywhere.", "Publish it and I behave.", "Orbiting."],
  boxy: [">_", "Ready.", "Segfault? Never met one.", "Exit code 0."],
  ghost: ["Boo.", "I outlive your sessions.", "Nobody sees my tenant.", "..."],
  sprout: ["Growing.", "Water me with tokens.", "Photosynthesising.", "Spring soon."],
  amigo: ["¡Hola!", "No more caramba.", "¡Ándale, agente!", "Siesta pending approval."],
};

/** One of a pet's lines, never the one it said last when it has more than one. */
export function pickLine(kind, random, last = null) {
  const lines = LINES[kind];
  const candidates = lines.length > 1 ? lines.filter((line) => line !== last) : lines;
  return candidates[Math.floor(random() * candidates.length)];
}
