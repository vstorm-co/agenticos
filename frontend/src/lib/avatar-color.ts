/**
 * The colour anyone - a person, an organization, an agent - wears when they
 * never uploaded a picture.
 *
 * Derived from what the client already holds, so a fresh deployment looks
 * designed rather than empty and no row costs a network request to draw. The
 * colour is a stable function of a seed (the row's id), so one entity wears the
 * same colour everywhere it appears.
 *
 * Two shapes read it. An organization draws two letters on the fill itself
 * (`avatarInitials` + `avatarPalette`); a person and an agent draw a generated
 * face, which takes the same choice as a hue (`avatarHue`) rather than as a
 * class. One picker, one stored slot, two renderers.
 */

/**
 * Up to two initials for a face nobody uploaded, or `""` when there is nothing
 * to take them from (the caller then draws a glyph).
 *
 * Splits on whitespace *and* `@`, so an account with no name still gets two
 * letters from its address ("kacper@vstorm.co" -> "KV") rather than one.
 * `charAt`, not `[0]`: it returns a string for any index, so
 * there is no impossible-empty case to guard and no dead branch to leave behind.
 */
export function avatarInitials(nameOrEmail: string): string {
  return nameOrEmail
    .split(/[\s@]/)
    .filter((part) => part.length > 0)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

export interface AvatarPalette {
  /** Background class, applied to the fallback circle. */
  bg: string;
  /** Foreground class, applied to the initials on it. */
  fg: string;
}

/**
 * Ten pastel fills on one charcoal ink, from the `--avatar-*` tokens in
 * `globals.css`. Referenced as arbitrary-value classes so the class strings
 * survive as literals for Tailwind to generate; the tokens are theme-independent
 * (see the ramp's comment there), so the chip reads in light and dark alike
 * without a `dark:` variant.
 */
const PALETTE: readonly AvatarPalette[] = [
  { bg: "bg-[var(--avatar-1)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-2)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-3)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-4)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-5)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-6)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-7)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-8)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-9)]", fg: "text-[var(--avatar-ink)]" },
  { bg: "bg-[var(--avatar-10)]", fg: "text-[var(--avatar-ink)]" },
];

/** How many colours the picker offers, and the top of the stored 1..N range. */
export const AVATAR_COLOR_COUNT = PALETTE.length;

/** Every colour, paired with the 1-based slot stored on the row - for the picker. */
export const AVATAR_COLORS: readonly { slot: number; palette: AvatarPalette }[] = PALETTE.map(
  (palette, i) => ({ slot: i + 1, palette }),
);

/** A slot's colour, or the hashed default when the slot is out of range or absent. */
function paletteForSlot(slot: number | null | undefined, seed: string): AvatarPalette {
  if (slot != null && slot >= 1 && slot <= AVATAR_COLOR_COUNT) {
    return PALETTE[slot - 1] as AvatarPalette;
  }
  return hashedPalette(seed);
}

function hashedPalette(seed: string): AvatarPalette {
  let hash = 5381;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 33) ^ seed.charCodeAt(i);
  }
  return PALETTE[(hash >>> 0) % PALETTE.length] as AvatarPalette;
}

/**
 * The hue of each `--avatar-*` fill, in degrees, in slot order.
 *
 * These are the `oklch(L C H)` hue channels from `globals.css` and nothing else:
 * a face drawn for slot 7 has to be the green the swatch that chose it shows,
 * or the picker is lying about what it picks. The two lists are written down in
 * different languages and cannot import from each other, so
 * `avatar-color.test.ts` reads the stylesheet back and fails when they drift.
 */
export const AVATAR_HUES: readonly number[] = [265, 300, 330, 20, 55, 95, 140, 175, 205, 240];

/**
 * The hue a generated face wears, or `undefined` when no slot is chosen.
 *
 * `undefined` is not a missing value here - it is what hands the colour back to
 * the generator, which derives one from the name across the whole circle rather
 * than from ten steps of it. That is what "auto" in the picker means, and it is
 * why this does not fall back to `hashedPalette` the way the class side does:
 * ten hues would be a worse default than the generator's own.
 */
export function avatarHue(colorSlot?: number | null): number | undefined {
  if (colorSlot != null && colorSlot >= 1 && colorSlot <= AVATAR_COLOR_COUNT) {
    return AVATAR_HUES[colorSlot - 1];
  }
  return undefined;
}

/**
 * The colour an entity wears. A chosen slot (1..N, what the row stores) wins;
 * otherwise it is derived from the seed, deterministic and stable so the same id
 * draws the same colour on every screen. A djb2 hash kept unsigned before the
 * modulo, because a negative index selects nothing.
 */
export function avatarPalette(seed: string, colorSlot?: number | null): AvatarPalette {
  return paletteForSlot(colorSlot, seed);
}
