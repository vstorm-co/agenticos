/**
 * The default face for anyone - a person, an organization, an agent - who never
 * uploaded one.
 *
 * Two letters on a colour, both derived from what the client already holds, so a
 * fresh deployment looks designed rather than empty and no row costs a network
 * request to draw. The colour is a stable function of a seed (the row's id), so
 * one entity wears the same colour everywhere it appears; the letters come from
 * the name, so a member list stays readable at a glance.
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

/**
 * The colour an entity wears, chosen by its seed. Deterministic and stable, so
 * the same id draws the same colour on every screen it appears on. A djb2 hash
 * kept unsigned before the modulo, because a negative index selects nothing.
 */
export function avatarPalette(seed: string): AvatarPalette {
  let hash = 5381;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 33) ^ seed.charCodeAt(i);
  }
  return PALETTE[(hash >>> 0) % PALETTE.length] as AvatarPalette;
}
