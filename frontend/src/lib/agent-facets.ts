/**
 * The agent discovery facet, shared by the query key and the request.
 *
 * One canonicalizer feeds both, so a selection keys a cache entry the same way
 * it is sent to the server - otherwise two different selections could reuse a
 * stale cached page. It sorts a *copy* and never mutates the array it is handed:
 * that array is React state, and sorting it in place corrupts the render.
 */

/** A stable, sorted copy of a facet selection. Never mutates the input. */
export function canonicalFacet(values: string[]): string[] {
  return [...values].sort();
}

/**
 * The repeated `category`/`tag` filters as tuple pairs.
 *
 * `RequestOptions.params` collapses an object's duplicate keys, so a repeated
 * key survives only as `[["category","a"],["category","b"]]` - the object form
 * would send one value for the whole facet.
 */
export function facetParams(categories: string[], tags: string[]): [string, string][] {
  return [
    ...categories.map((value): [string, string] => ["category", value]),
    ...tags.map((value): [string, string] => ["tag", value]),
  ];
}

/**
 * The `GET /agents` query params for a listing.
 *
 * `undefined` when nothing narrows the list, so the plain listing keeps sharing
 * one cache entry with every other unfiltered reader (the command palette, the
 * onboarding coach). A facet is emitted as tuple pairs, with `include_archived`
 * folded in beside it.
 */
export function agentListParams(
  includeArchived: boolean,
  categories: string[],
  tags: string[],
): Record<string, string> | [string, string][] | undefined {
  const pairs = facetParams(categories, tags);
  if (pairs.length === 0) {
    return includeArchived ? { include_archived: "true" } : undefined;
  }
  return includeArchived ? [["include_archived", "true"], ...pairs] : pairs;
}
