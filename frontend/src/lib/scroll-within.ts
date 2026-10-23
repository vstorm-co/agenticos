/** Where in its scroller an element is brought to, as `scrollIntoView`'s `block` says it. */
export type ScrollBlock = "start" | "center" | "nearest";

function scrollerOf(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") return node;
  }
  return null;
}

/**
 * Scrolls an element into view by moving its nearest scrollable ancestor only.
 *
 * `scrollIntoView` moves every scrollable ancestor it has, so a page column
 * that can scroll at all is dragged along with the chat inside it. An element
 * no scroller holds is left where it is.
 */
export function scrollWithin(
  element: HTMLElement,
  block: ScrollBlock,
  behavior: ScrollBehavior,
): void {
  const scroller = scrollerOf(element);
  if (scroller === null) return;
  const view = scroller.clientHeight;
  const box = element.getBoundingClientRect();
  // How far the element's top sits below the top of the scroller's viewport.
  const offset = box.top - scroller.getBoundingClientRect().top;
  let top = scroller.scrollTop + offset;
  if (block === "center") {
    top -= (view - box.height) / 2;
  } else if (block === "nearest") {
    const overhang = offset + box.height - view;
    if (offset >= 0 && overhang <= 0) return;
    if (offset > 0 && box.height <= view) top = scroller.scrollTop + overhang;
  }
  scroller.scrollTo({ top, behavior });
}
