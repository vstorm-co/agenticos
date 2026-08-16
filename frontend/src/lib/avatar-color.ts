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
 * Ten pairs legible in both themes: a translucent tint for the circle and a
 * solid ink for the letters, the ink lightened under `dark`. Written as literal
 * class strings so Tailwind keeps them - a computed `bg-${hue}-500/15` is purged.
 */
const PALETTE: readonly AvatarPalette[] = [
  { bg: "bg-indigo-500/15", fg: "text-indigo-700 dark:text-indigo-300" },
  { bg: "bg-sky-500/15", fg: "text-sky-700 dark:text-sky-300" },
  { bg: "bg-teal-500/15", fg: "text-teal-700 dark:text-teal-300" },
  { bg: "bg-emerald-500/15", fg: "text-emerald-700 dark:text-emerald-300" },
  { bg: "bg-amber-500/15", fg: "text-amber-700 dark:text-amber-300" },
  { bg: "bg-orange-500/15", fg: "text-orange-700 dark:text-orange-300" },
  { bg: "bg-rose-500/15", fg: "text-rose-700 dark:text-rose-300" },
  { bg: "bg-violet-500/15", fg: "text-violet-700 dark:text-violet-300" },
  { bg: "bg-fuchsia-500/15", fg: "text-fuchsia-700 dark:text-fuchsia-300" },
  { bg: "bg-cyan-500/15", fg: "text-cyan-700 dark:text-cyan-300" },
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
