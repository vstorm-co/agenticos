/** Separate an optional YAML frontmatter block without parsing or rewriting the source. */
export function markdownDocument(source: string): { frontmatter: string | null; body: string } {
  const match = /^(?:\uFEFF)?---\r?\n([\s\S]*?)^(?:---|\.\.\.)(?:\r?\n|$)/m.exec(source);
  if (!match || match.index !== 0) return { frontmatter: null, body: source };
  return { frontmatter: match[1] ?? "", body: source.slice(match[0].length) };
}
