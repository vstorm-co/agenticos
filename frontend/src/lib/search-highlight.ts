/** One run of a result's text, and whether it matched the query. */
export interface HighlightSegment {
  text: string;
  match: boolean;
}

/** Words shorter than this mark too much to point at anything ("a", "of", "in"). */
const MIN_TERM_LENGTH = 3;

const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Split `text` into the runs that match `query` and the runs that do not.
 *
 * Search is semantic, so a result may contain none of the query's words; then
 * the whole text comes back as one unmatched run. The exact phrase wins when it
 * appears, so a pasted sentence lights up as one span rather than word by word;
 * otherwise each word of at least three letters is marked wherever it occurs.
 * Case is ignored either way.
 */
export function highlightSegments(text: string, query: string): HighlightSegment[] {
  const phrase = query.trim().replace(/\s+/g, " ");
  if (!text || !phrase) return [{ text, match: false }];
  const phrasePattern = new RegExp(escape(phrase).replace(/ /g, "\\s+"), "giu");
  const pattern = phrasePattern.test(text) ? phrasePattern : termPattern(phrase);
  if (pattern === null) return [{ text, match: false }];
  pattern.lastIndex = 0;
  const segments: HighlightSegment[] = [];
  let at = 0;
  for (const found of text.matchAll(pattern)) {
    const start = found.index;
    if (start > at) segments.push({ text: text.slice(at, start), match: false });
    segments.push({ text: found[0], match: true });
    at = start + found[0].length;
  }
  if (at < text.length) segments.push({ text: text.slice(at), match: false });
  return segments;
}

function termPattern(phrase: string): RegExp | null {
  const terms = [
    ...new Set(
      phrase
        .toLocaleLowerCase()
        .split(/[^\p{L}\p{N}]+/u)
        .filter((term) => term.length >= MIN_TERM_LENGTH),
    ),
  ];
  if (terms.length === 0) return null;
  // Longest first, so a word is not cut short by a shorter query word inside it.
  terms.sort((a, b) => b.length - a.length);
  return new RegExp(terms.map(escape).join("|"), "giu");
}
