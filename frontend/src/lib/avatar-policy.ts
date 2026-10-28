import type { TraitOverrides } from "blobatar";

/**
 * Blobatar 2.7 trait positions, not SVG dimensions. Keep its seeded variation
 * within round, organic and soft boxy silhouettes; tiny portraits need a face,
 * rather than lobes, a flattened capsule or a near-black body.
 */
export const AVATAR_TRAITS: TraitOverrides = {
  shape: [0.1, 0.34, 0.54],
  tone: [0.1, 0.45, 0.85],
  "body.r": 0.75,
  "body.ratio": 0.5,
  "body.rot": 0.55,
  "body.n": 0.35,
  "body.r0": [0.35, 0.5, 0.65],
  "body.r1": [0.35, 0.5, 0.65],
  "body.r2": [0.35, 0.5, 0.65],
  "body.r3": [0.35, 0.5, 0.65],
  "body.r4": [0.35, 0.5, 0.65],
  "body.r5": [0.35, 0.5, 0.65],
  "body.r6": [0.35, 0.5, 0.65],
  "body.r7": [0.35, 0.5, 0.65],

  "eye.scale": 0.45,
  "eye.stretch": 0.45,
  "eye.ratio": 0.45,
  "eye.lean": 0.5,
  "eye.lean2": 0.5,
};
