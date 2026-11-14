function words(text: string): Set<string> {
  return new Set(text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []);
}

function overlap(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let shared = 0;
  for (const word of a) if (b.has(word)) shared++;
  return shared / (a.size + b.size - shared);
}

/**
 * Cases ordered by how many words their question shares with `question`.
 *
 * The share of words the two have in common, so the case asking the same
 * question comes first and a rewording follows; ties keep the dataset's order.
 * Only the cases given are ranked, which is the page on screen.
 */
export function similarFirst<T extends { input: string }>(cases: T[], question: string): T[] {
  const asked = words(question);
  return cases
    .map((item, index) => ({ item, index, score: overlap(words(item.input), asked) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map(({ item }) => item);
}
