/**
 * The editor's working model: an arrangement as a list of sections, each the
 * divider heading it (or none, for the leading group) plus the cards beneath.
 *
 * The persisted form is a flat item list (see `lib/dashboard/preference.ts`);
 * this is the shape the editor mutates, and the two convert at the edges
 * (`toEditorSections` on open, `fromEditorSections` on save). Working in
 * sections is what makes each section its own independent grid — a card only
 * ever belongs to one section's list, so dragging it into another is a move
 * between lists, and the dense-packing of one section can never pull a card up
 * across a divider into another.
 *
 * Every section and every card carries a `uid` that lives only for the edit
 * session. It is never persisted; its whole job is to stay stable across a
 * reorder so the FLIP animation matches a card's old position to its new one
 * and React moves the node rather than rebuilding it.
 */

import { groupItems, ungroupItems, type ItemSection } from "@/lib/dashboard/preference";
import type { DividerEntry, LayoutEntry, LayoutItem } from "@/lib/dashboard/layouts";
import type { Rows, Span } from "@/lib/dashboard/registry";

export type EditorWidget = LayoutEntry & { uid: string };
export interface EditorSection {
  uid: string;
  /** The divider heading this section, or null for the leading (pre-divider) group. */
  divider: DividerEntry | null;
  widgets: EditorWidget[];
}

/** Group a flat item list into editor sections, minting a uid for each. */
export function toEditorSections(items: LayoutItem[], mint: () => string): EditorSection[] {
  return groupItems(items).map((section: ItemSection) => ({
    uid: mint(),
    divider: section.divider,
    widgets: section.widgets.map((widget) => ({ ...widget, uid: mint() })),
  }));
}

/** Flatten editor sections back to the flat item list the wire form is built from. */
export function fromEditorSections(sections: EditorSection[]): LayoutItem[] {
  return ungroupItems(
    sections.map((section) => ({
      divider: section.divider,
      widgets: section.widgets.map(({ uid: _uid, ...widget }) => widget),
    })),
  );
}

/** Where a card currently sits, for skipping a reorder that would change nothing. */
export function locate(
  sections: EditorSection[],
  widgetUid: string,
): { sectionUid: string; index: number } | null {
  for (const section of sections) {
    const index = section.widgets.findIndex((widget) => widget.uid === widgetUid);
    if (index >= 0) return { sectionUid: section.uid, index };
  }
  return null;
}

/**
 * Move a card to `index` within the target section, from wherever it was. The
 * index is read in the space of the target section's *other* cards (the dragged
 * one removed first), which is what the pointer hit-test produces.
 */
export function moveWidget(
  sections: EditorSection[],
  widgetUid: string,
  toSectionUid: string,
  index: number,
): EditorSection[] {
  let moved: EditorWidget | undefined;
  const stripped = sections.map((section) => {
    if (!section.widgets.some((widget) => widget.uid === widgetUid)) return section;
    moved = section.widgets.find((widget) => widget.uid === widgetUid);
    return { ...section, widgets: section.widgets.filter((widget) => widget.uid !== widgetUid) };
  });
  if (!moved) return sections;
  const card = moved;
  return stripped.map((section) => {
    if (section.uid !== toSectionUid) return section;
    const widgets = section.widgets.slice();
    widgets.splice(Math.min(Math.max(index, 0), widgets.length), 0, card);
    return { ...section, widgets };
  });
}

/**
 * Exchange two cards, each taking the other's slot — and its section, when they
 * sit in different ones. This is the drop-on-a-tile gesture: releasing a dragged
 * card over another swaps the pair in either direction with no midpoint to
 * cross, so a card lands the moment the pointer is over its target rather than
 * only once it has passed the target's centre. A no-op if the two are the same
 * or either is missing.
 */
export function swapWidgets(
  sections: EditorSection[],
  firstUid: string,
  secondUid: string,
): EditorSection[] {
  if (firstUid === secondUid) return sections;
  let firstCard: EditorWidget | undefined;
  let secondCard: EditorWidget | undefined;
  for (const section of sections) {
    for (const widget of section.widgets) {
      if (widget.uid === firstUid) firstCard = widget;
      else if (widget.uid === secondUid) secondCard = widget;
    }
  }
  if (!firstCard || !secondCard) return sections;
  const first = firstCard;
  const second = secondCard;
  return sections.map((section) => ({
    ...section,
    widgets: section.widgets.map((widget) =>
      widget.uid === firstUid ? second : widget.uid === secondUid ? first : widget,
    ),
  }));
}

/**
 * Move a card one step earlier (`-1`) or later (`+1`) in reading order across
 * the whole arrangement — the keyboard counterpart to a drag. It swaps the card
 * with its neighbour, so a step off the end of one section carries it into the
 * next (the neighbour takes the vacated slot), the same exchange the drop-on-a-
 * tile gesture makes. A no-op at the very ends, where there is no neighbour.
 *
 * A step that lands the card in a collapsed section unfolds it, so the card is
 * never swapped into a folded band where it reads as vanished — the same answer
 * the add path gives, and the case the pointer hit-test skips outright.
 */
export function moveWidgetBy(
  sections: EditorSection[],
  widgetUid: string,
  direction: -1 | 1,
): EditorSection[] {
  const order = sections.flatMap((section) => section.widgets.map((widget) => widget.uid));
  const at = order.indexOf(widgetUid);
  if (at < 0) return sections;
  const neighbour = order[at + direction];
  if (neighbour === undefined) return sections;
  const swapped = swapWidgets(sections, widgetUid, neighbour);
  const landing = swapped.find((section) =>
    section.widgets.some((widget) => widget.uid === widgetUid),
  );
  return landing?.divider?.collapsed
    ? patchDivider(swapped, landing.uid, { collapsed: false })
    : swapped;
}

/**
 * Move a whole section to `index`, reordering among the other sections. A
 * headingless leading section is pinned to the front — its cards have no divider
 * to travel with — so both the moved section and the target index stay past it.
 */
export function moveSection(
  sections: EditorSection[],
  sectionUid: string,
  index: number,
): EditorSection[] {
  const from = sections.findIndex((section) => section.uid === sectionUid);
  const moving = from < 0 ? undefined : sections[from];
  if (!moving || moving.divider === null) return sections;
  const floor = sections[0]?.divider === null ? 1 : 0;
  const next = sections.slice();
  next.splice(from, 1);
  next.splice(Math.min(Math.max(index, floor), next.length), 0, moving);
  return next;
}

/**
 * Move a whole section one step earlier (`-1`) or later (`+1`) among the other
 * sections — the keyboard counterpart to dragging its grip. A no-op at the ends,
 * and for the pinned headingless leading section, whose cards have no divider to
 * travel with.
 */
export function moveSectionBy(
  sections: EditorSection[],
  sectionUid: string,
  direction: -1 | 1,
): EditorSection[] {
  const at = sections.findIndex((section) => section.uid === sectionUid);
  const moving = at < 0 ? undefined : sections[at];
  if (!moving || moving.divider === null) return sections;
  const floor = sections[0]?.divider === null ? 1 : 0;
  const target = at + direction;
  if (target < floor || target >= sections.length) return sections;
  return moveSection(sections, sectionUid, target);
}

/** Resize the card to a width and height from the grid's closed sets. */
export function resizeWidget(
  sections: EditorSection[],
  widgetUid: string,
  span: Span,
  rows: Rows,
): EditorSection[] {
  return sections.map((section) => ({
    ...section,
    widgets: section.widgets.map((widget) =>
      widget.uid === widgetUid ? { ...widget, span, rows } : widget,
    ),
  }));
}

/** Drop a card from the arrangement. */
export function removeWidget(sections: EditorSection[], widgetUid: string): EditorSection[] {
  return sections.map((section) => ({
    ...section,
    widgets: section.widgets.filter((widget) => widget.uid !== widgetUid),
  }));
}

/** Append a card to the end of a section. */
export function addWidgetToSection(
  sections: EditorSection[],
  sectionUid: string,
  widget: EditorWidget,
): EditorSection[] {
  return sections.map((section) =>
    section.uid === sectionUid ? { ...section, widgets: [...section.widgets, widget] } : section,
  );
}

/**
 * Remove a section's heading, merging its cards into the previous section (or
 * the leading group). With no previous section the cards become a new
 * headingless leading section, so removing a heading never removes cards.
 */
export function removeSection(sections: EditorSection[], sectionUid: string): EditorSection[] {
  const index = sections.findIndex((section) => section.uid === sectionUid);
  const section = index < 0 ? undefined : sections[index];
  if (!section) return sections;
  const next = sections.slice();
  next.splice(index, 1);
  if (section.widgets.length === 0) return next;
  const previous = next[index - 1];
  if (previous) {
    next[index - 1] = { ...previous, widgets: [...previous.widgets, ...section.widgets] };
    return next;
  }
  return [{ uid: section.uid, divider: null, widgets: section.widgets }, ...next];
}

/** Change a section's heading — its label, accent or collapse. */
export function patchDivider(
  sections: EditorSection[],
  sectionUid: string,
  patch: Partial<DividerEntry>,
): EditorSection[] {
  return sections.map((section) =>
    section.uid === sectionUid && section.divider
      ? { ...section, divider: { ...section.divider, ...patch } }
      : section,
  );
}
