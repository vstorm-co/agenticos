import { layout } from "blobatar/blob";
import { traits } from "blobatar";
import { expect, it } from "vitest";
import { AVATAR_TRAITS } from "./avatar-policy";

it("keeps a broad seed sample legible and within compact portrait silhouettes", () => {
  const shapes = new Set<string>();
  for (let index = 0; index < 500; index++) {
    const face = layout(traits(`agent-${index}`, true, AVATAR_TRAITS));
    shapes.add(face.shape);
    expect(face.body.ry / face.body.rx).toBeCloseTo(1);
    expect(Math.abs(face.body.rot)).toBeLessThan(5);
    for (const eye of face.eyes) {
      expect(eye.ry).toBeGreaterThan(eye.rx);
      expect(Math.abs(eye.cx - face.body.cx) + eye.rx).toBeLessThan(face.body.rx);
      expect(Math.abs(eye.cy - face.body.cy) + eye.ry).toBeLessThan(face.body.ry);
    }
  }
  expect(shapes).toEqual(new Set(["round", "organic", "boxy"]));
});
