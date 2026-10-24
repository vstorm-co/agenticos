import {
  HIDDEN_CATEGORIES,
  PICKER_SECTIONS,
  categoryRank,
  operationRank,
} from "@/components/workflows/node-visuals";
import type { NodeDefinition } from "@/lib/workflows/types";

/** One group of steps - a catalog `category`, such as `slack` or `tables`. */
export interface PickerGroup {
  category: string;
  items: NodeDefinition[];
}

/** A heading in the picker and the groups under it. */
export interface PickerSection {
  id: string;
  groups: PickerGroup[];
}

/** The section that collects a category no section names. */
export const MORE_SECTION = "more";

/**
 * The offered steps as the picker lists them: sections in the order a workflow
 * reads, each with its groups, each group's steps in catalog order. Empty
 * groups and sections are left out, and a hidden category never shows. A chat
 * platform's steps are listed acting first: send, read, list, find.
 */
export function pickerSections(definitions: readonly NodeDefinition[]): PickerSection[] {
  const byCategory = new Map<string, NodeDefinition[]>();
  for (const definition of definitions) {
    if (HIDDEN_CATEGORIES.has(definition.category)) continue;
    const items = byCategory.get(definition.category) ?? [];
    items.push(definition);
    byCategory.set(definition.category, items);
  }
  // Stable, so a group with no operation order keeps the catalog's.
  for (const items of byCategory.values()) {
    items.sort((a, b) => operationRank(a.id) - operationRank(b.id));
  }
  const named = new Set<string>(PICKER_SECTIONS.flatMap((section) => section.groups));
  const sections: PickerSection[] = PICKER_SECTIONS.map((section) => ({
    id: section.id,
    groups: section.groups.flatMap((category) => {
      const items = byCategory.get(category);
      return items === undefined ? [] : [{ category, items }];
    }),
  }));
  const rest = [...byCategory.keys()]
    .filter((category) => !named.has(category))
    .sort((a, b) => categoryRank(a) - categoryRank(b) || a.localeCompare(b))
    .map((category) => ({ category, items: byCategory.get(category) ?? [] }));
  sections.push({ id: MORE_SECTION, groups: rest });
  return sections.filter((section) => section.groups.length > 0);
}

/** Whether a step answers a search, by its name, what it does or its group. */
export function matchesSearch(
  definition: NodeDefinition,
  query: string,
  groupLabel: string,
): boolean {
  const needle = query.trim().toLowerCase();
  if (needle === "") return true;
  return [definition.name, definition.description, groupLabel].some((text) =>
    text.toLowerCase().includes(needle),
  );
}
