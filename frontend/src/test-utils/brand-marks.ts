import { BRAND_GLYPHS, PROVIDER_GLYPHS, type Glyph } from "@/lib/brand-glyphs.generated";

/**
 * Which mark an element actually draws, named by the id the product uses.
 *
 * Six specs used to answer this by reading the source SVG's `<title>` -
 * `svg > title` said "OpenRouter" - which worked only for as long as the marks
 * came from a package that shipped one. They do not: `gen-brand-icons.ts` drops
 * the title deliberately, because every row prints the provider beside its icon
 * and a mark that names itself makes a screen reader say it twice.
 *
 * So the mark is identified by what it is: its path data, which is unique per
 * brand. That makes this a stricter check than the title ever was - a title only
 * proved *a* mark rendered under that name, where this proves the drawn shape is
 * the one the set holds for that id (#156).
 *
 * Every path under `element` is considered, not the first: a row draws the mark
 * beside a lucide tick and a chevron, and whichever the DOM happens to put first
 * is not the question being asked. Deliberately outside the coverage `include`
 * list, so a test helper does not drag the 100% gate along.
 */
function nameOf(element: Element | null, glyphs: Readonly<Record<string, Glyph>>): string | null {
  const drawn = new Set(
    [...(element?.querySelectorAll("svg path") ?? [])].map((path) => path.getAttribute("d")),
  );
  const match = Object.entries(glyphs).find(([, glyph]) => drawn.has(glyph.paths[0]?.d ?? null));
  return match === undefined ? null : match[0];
}

/** The model-provider id whose mark `element` draws, or `null` for none. */
export function providerMarkIn(element: Element | null): string | null {
  return nameOf(element, PROVIDER_GLYPHS);
}

/** The brand name whose mark `element` draws, or `null` for none. */
export function brandMarkIn(element: Element | null): string | null {
  return nameOf(element, BRAND_GLYPHS);
}
