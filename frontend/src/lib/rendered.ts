/**
 * Whether an element is actually rendered — nothing in its ancestry is
 * `display: none` or `visibility: hidden`.
 *
 * The navigation exists twice: the desktop column is `hidden … md:flex`, so below
 * that breakpoint it stays in the document with `display: none` while the real
 * navigation lives in a sheet that is not mounted until it is opened. A plain
 * `querySelector` therefore hands the walk the *hidden* link, whose box measures
 * zero — a full-viewport freeze with a 0×0 cut-out, over a page whose hamburger is
 * now unreachable, on a step that waits for a click nobody can make.
 *
 * Measured with computed style rather than `offsetParent` or `getClientRects`,
 * both of which report every element as hidden under jsdom and would make this
 * unfalsifiable in a unit test.
 */
export function isRendered(element: Element): boolean {
  for (let node: Element | null = element; node !== null; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") return false;
  }
  return true;
}
