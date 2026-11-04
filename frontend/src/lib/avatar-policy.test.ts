import { layout } from "blobatar/blob";
import { traits, ramp, contrast, palette } from "blobatar";
import { expect, it } from "vitest";
import { AVATAR_TRAITS, portraitHue } from "./avatar-policy";

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

it("keeps automatic colors in the clean palette and honors explicit colors", () => {
  const hues = new Set<number>();
  for (let i = 0; i < 500; i++) {
    const hue = portraitHue(`agent-${i}`);
    hues.add(hue);
    expect(hue).toBeGreaterThanOrEqual(0);
    expect(hue).toBeLessThan(360);
    expect(hue < 55 || hue >= 115).toBe(true);
    expect(hue).toBe(portraitHue(`agent-${i}`));
  }
  expect(hues.size).toBeGreaterThan(490);
  expect(portraitHue("agent", 5)).toBe(55);
  expect(portraitHue("agent", 6)).toBe(95);
  expect(portraitHue("agent", null)).toBe(portraitHue("agent"));
});

it("keeps clean tones readable without collapsing the palette to a handful of colors", () => {
  const fills = new Set<string | undefined>();
  for (let i = 0; i < 500; i++) {
    const hue = portraitHue(`agent-${i}`);
    const tone = traits(`agent-${i}`, true, AVATAR_TRAITS)("tone");
    expect([0.1, 0.85]).toContain(tone);
    const colors = ramp(hue, true, tone);
    expect(contrast(colors.eye!, colors.head!)).toBeGreaterThanOrEqual(4.5);
    fills.add(palette(hue, true, tone).head);
  }
  expect(fills.size).toBeGreaterThan(300);
});

it("spreads the gallery's real handles across warm and cool hues", () => {
  const hues = [
    "browser_agent",
    "background-browse-demo-1792144884",
    "supplier-invoice-policy-helper",
    "claude-code-like",
    "support-copilot",
    "test",
    "browser-check",
  ].map((seed) => portraitHue(seed));
  expect(hues.some((hue) => hue < 55)).toBe(true);
  expect(hues.some((hue) => hue > 240)).toBe(true);
  expect(new Set(hues.map((hue) => Math.floor(hue / 45))).size).toBeGreaterThanOrEqual(6);
});
