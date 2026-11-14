/** JSON wire content, independent of object key order; array order remains meaningful. */
export function canonicalJson(value: unknown): string {
  return (
    JSON.stringify(value, (_key: string, item: unknown): unknown => {
      if (item !== null && typeof item === "object" && !Array.isArray(item)) {
        const entries: [string, unknown][] = Object.entries(item);
        entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
        return Object.fromEntries(entries);
      }
      return item;
    }) ?? "undefined"
  );
}

export function sameJson(left: unknown, right: unknown): boolean {
  return canonicalJson(left) === canonicalJson(right);
}
