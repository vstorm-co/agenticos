/**
 * The sections filter: an ephemeral "show me only these" over the layout.
 *
 * State lives in the URL (`?sections=attention,usage`), nothing is persisted,
 * and the filter can only ever hide - it operates on the sections that
 * survived the permission gates, so a stored or pasted id can never reveal a
 * section the caller may not see. That property is what separates this from
 * the user-arranged dashboard, which stayed out of v1.
 */

import type { SectionDef } from "./layouts";

/**
 * Whether the filter may offer a section - it must have a name to offer.
 *
 * A curated section is named by a `titleKey`; a band a person made with their
 * own divider is named by the `title` they typed. Both are names, and reading
 * only the first meant the whole control disappeared the moment somebody saved
 * an arrangement, even one that kept every heading it started with.
 *
 * An unnamed section is structural - the member's whole page is one, and so is
 * the summary band above every other layout - and offering to hide it would
 * offer an empty dashboard.
 */
export function isFilterable(section: SectionDef): boolean {
  return section.titleKey !== null || !!section.title?.trim();
}

/** The heading a section shows, from whichever of its two names it carries. */
export function sectionLabel(section: SectionDef, t: (key: string) => string): string {
  if (section.title?.trim()) return section.title;
  return section.titleKey ? t(`sections.${section.titleKey}`) : "";
}

/** Which section ids the filter may offer. */
export function filterableSectionIds(sections: SectionDef[]): string[] {
  return sections.filter(isFilterable).map((section) => section.id);
}

/**
 * Read `?sections=` against the sections the caller can actually see.
 * Unknown ids are dropped; an empty or fully-invalid selection answers null,
 * which means "no filter" - the control never filters down to nothing.
 */
export function parseSectionsParam(value: string | null, sections: SectionDef[]): string[] | null {
  if (!value) return null;
  const available = new Set(filterableSectionIds(sections));
  const selected = value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => available.has(part));
  if (selected.length === 0 || selected.length === available.size) return null;
  return selected;
}

/** Apply the selection: a section the filter never offered always stays. */
export function applySectionsFilter(
  sections: SectionDef[],
  selected: string[] | null,
): SectionDef[] {
  if (selected === null) return sections;
  const keep = new Set(selected);
  return sections.filter((section) => !isFilterable(section) || keep.has(section.id));
}

/** The URL form; null clears the parameter. */
export function formatSectionsParam(selected: string[] | null): string | null {
  return selected === null || selected.length === 0 ? null : selected.join(",");
}
