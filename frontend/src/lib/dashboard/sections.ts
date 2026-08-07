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
 * Which section ids the filter may offer: only titled ones. An untitled
 * section is structural - the member's whole page is one - and offering to
 * hide it would offer an empty dashboard.
 */
export function filterableSectionIds(sections: SectionDef[]): string[] {
  return sections.filter((section) => section.titleKey !== null).map((section) => section.id);
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

/** Apply the selection: untitled sections always stay. */
export function applySectionsFilter(
  sections: SectionDef[],
  selected: string[] | null,
): SectionDef[] {
  if (selected === null) return sections;
  const keep = new Set(selected);
  return sections.filter((section) => section.titleKey === null || keep.has(section.id));
}

/** The URL form; null clears the parameter. */
export function formatSectionsParam(selected: string[] | null): string | null {
  return selected === null || selected.length === 0 ? null : selected.join(",");
}
