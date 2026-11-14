/** Format a new human-entered identifier; never invent a fallback or shorten it. */
export function normalizeIdentifier(value: string): string {
  return value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/\p{M}/gu, "")
    .replace(/ł/g, "l")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
