import { NAV_GROUPS, navSectionFor, type NavGroup, type NavItem } from "@/lib/nav-sections";

/**
 * The sidebar a person sees: four fixed entries, the items they pinned, the
 * page they are on when it is neither, and a More panel holding the rest.
 *
 * Pure functions over `NAV_GROUPS`, so the sidebar, its tests and the pin
 * toggles all answer the same questions. A pin is only an id: it never grants
 * access, so every id is resolved against the table and the caller's
 * `isVisible` (permissions plus the role's navigation choices) on each render.
 */

/** The group with no heading is the fixed one: Home, Chat, Inbox and Agent messages. */
const FIXED_ITEMS: readonly NavItem[] = NAV_GROUPS.filter(
  (group) => group.labelKey === null,
).flatMap((group) => group.items);
const LISTED_GROUPS: readonly NavGroup[] = NAV_GROUPS.filter((group) => group.labelKey !== null);

/** A stable id for an entry. The label key is what role navigation choices already store. */
export function navItemId(item: NavItem): string {
  return item.labelKey;
}

const FIXED_IDS: ReadonlySet<string> = new Set(FIXED_ITEMS.map(navItemId));

const PINNABLE: ReadonlyMap<string, NavItem> = new Map(
  LISTED_GROUPS.flatMap((group) => group.items.map((item) => [navItemId(item), item])),
);

/** Whether an id names an entry that can be pinned: known, and not one of the fixed four. */
export function isPinnable(id: string): boolean {
  return PINNABLE.has(id);
}

export type MoreSection = {
  /** `null` for the admin entry, which closes the panel without a heading. */
  labelKey: string | null;
  items: NavItem[];
};

export type NavLayout = {
  fixed: NavItem[];
  pinned: NavItem[];
  /** The page being viewed, when it is neither fixed nor pinned; shown only while on it. */
  current: NavItem | null;
  more: MoreSection[];
};

export function buildNavLayout({
  pinnedIds,
  pathname,
  isVisible,
  isAdmin,
}: {
  pinnedIds: readonly string[];
  pathname: string;
  isVisible: (item: NavItem) => boolean;
  isAdmin: boolean;
}): NavLayout {
  const fixed = FIXED_ITEMS.filter(isVisible);

  const visibleById = new Map<string, NavItem>();
  const more: MoreSection[] = [];
  for (const group of LISTED_GROUPS) {
    const items = group.adminOnly && !isAdmin ? [] : group.items.filter(isVisible);
    for (const item of items) visibleById.set(navItemId(item), item);
    if (items.length > 0) {
      more.push({ labelKey: group.adminOnly ? null : group.labelKey, items });
    }
  }

  const pinned: NavItem[] = [];
  for (const id of new Set(pinnedIds)) {
    const item = visibleById.get(id);
    if (item) pinned.push(item);
  }

  const here = navSectionFor(pathname)?.item;
  const current =
    here &&
    visibleById.has(navItemId(here)) &&
    !FIXED_IDS.has(navItemId(here)) &&
    !pinned.includes(here)
      ? here
      : null;

  return { fixed, pinned, current, more };
}

/**
 * The ids to store after toggling `id`: the saved ids minus any this build no
 * longer knows, with `id` removed when pinned and appended when not.
 */
export function toggledPins(saved: readonly string[], id: string): string[] {
  const kept = saved.filter((saved_id) => isPinnable(saved_id) && saved_id !== id);
  return saved.includes(id) ? kept : [...kept, id];
}
