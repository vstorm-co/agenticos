import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  AVATAR_COLORS,
  AVATAR_COLOR_COUNT,
  AVATAR_HUES,
  avatarHue,
  avatarInitials,
  avatarPalette,
} from "./avatar-color";

/**
 * The letters and the colour a face nobody uploaded is drawn from. Both are
 * derived from what the client already holds, so the tests are about what the
 * derivation guarantees: readable letters, and a colour that never moves.
 */
describe("avatarInitials", () => {
  it("takes the first letter of the first two words", () => {
    expect(avatarInitials("Kacper Wlodarczyk")).toBe("KW");
  });

  it("takes a letter from either side of an address with no name", () => {
    // Splitting on `@` too means "kacper@vstorm.co" gives "KV", not one letter
    // from the whole address.
    expect(avatarInitials("kacper@vstorm.co")).toBe("KV");
  });

  it("takes one letter from a single word", () => {
    expect(avatarInitials("Support")).toBe("S");
  });

  it("ignores the whitespace somebody left in a name", () => {
    expect(avatarInitials("  Anna   Nowak  ")).toBe("AN");
  });

  it("has nothing to show for a name that is only whitespace", () => {
    // Which is what sends the fallback to a glyph rather than a blank circle.
    expect(avatarInitials("   ")).toBe("");
  });
});

describe("avatarPalette", () => {
  it("gives one seed the same colour every time", () => {
    expect(avatarPalette("org-42")).toEqual(avatarPalette("org-42"));
  });

  it("only ever answers with a background and a foreground class", () => {
    const { bg, fg } = avatarPalette("user-1");
    expect(bg).toMatch(/^bg-/);
    expect(fg).toMatch(/^text-/);
  });

  it("stays in range for a seed whose hash is large", () => {
    // The hash is masked unsigned before the modulo; a negative index would
    // select nothing.
    const seed = "z".repeat(64);
    expect(avatarPalette(seed).bg).toMatch(/^bg-/);
  });

  it("does not hand every seed the same colour", () => {
    const colours = new Set(Array.from({ length: 50 }, (_, i) => avatarPalette(`seed-${i}`).bg));
    expect(colours.size).toBeGreaterThan(1);
  });

  it("lets a chosen slot override the hash, ignoring the seed", () => {
    // A user who picked slot 3 wears slot 3 whatever their id hashes to.
    expect(avatarPalette("anything", 3)).toEqual(AVATAR_COLORS[2]!.palette);
    expect(avatarPalette("other", 3)).toEqual(avatarPalette("different", 3));
  });

  it("falls back to the hash for a null slot or one out of range", () => {
    const hashed = avatarPalette("seed-x");
    expect(avatarPalette("seed-x", null)).toEqual(hashed);
    expect(avatarPalette("seed-x", 0)).toEqual(hashed);
    expect(avatarPalette("seed-x", AVATAR_COLOR_COUNT + 1)).toEqual(hashed);
  });
});

describe("AVATAR_COLORS", () => {
  it("offers one entry per slot, numbered from one", () => {
    expect(AVATAR_COLORS).toHaveLength(AVATAR_COLOR_COUNT);
    expect(AVATAR_COLORS[0]!.slot).toBe(1);
    expect(AVATAR_COLORS.at(-1)!.slot).toBe(AVATAR_COLOR_COUNT);
  });
});

describe("avatarHue", () => {
  it("gives a chosen slot the hue of the swatch that chose it", () => {
    // Slot 7 is the green one in the picker, so a face picked there is drawn at
    // the green one's hue and not at some other green.
    expect(avatarHue(7)).toBe(AVATAR_HUES[6]);
  });

  it("hands the colour back to the generator when nothing was chosen", () => {
    // Not a hole: `undefined` is what lets the generator derive a hue from the
    // name across the whole circle, which is what "auto" in the picker means.
    expect(avatarHue(null)).toBeUndefined();
    expect(avatarHue()).toBeUndefined();
  });

  it("hands it back for a slot out of range too", () => {
    expect(avatarHue(0)).toBeUndefined();
    expect(avatarHue(AVATAR_COLOR_COUNT + 1)).toBeUndefined();
  });

  it("has a hue for every slot the picker offers", () => {
    expect(AVATAR_HUES).toHaveLength(AVATAR_COLOR_COUNT);
  });

  it("matches the hue channel of every `--avatar-*` token", () => {
    // The two lists are written in different languages and cannot import from
    // each other. This is what stops the picker showing one colour and the face
    // it picks wearing another.
    const css = readFileSync(join(__dirname, "../app/globals.css"), "utf8");
    const hues = AVATAR_HUES.map((_, i) => {
      const token = new RegExp(`--avatar-${i + 1}:\\s*oklch\\([^)]*?([\\d.]+)\\s*\\)`);
      return Number(css.match(token)?.[1]);
    });

    expect(hues).toEqual([...AVATAR_HUES]);
  });
});
