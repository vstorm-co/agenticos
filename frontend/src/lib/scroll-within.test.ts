import { afterEach, describe, expect, it, vi } from "vitest";

import { scrollWithin } from "./scroll-within";

/**
 * A scroller whose viewport starts 100px down the screen and is 400px tall,
 * scrolled `scrollTop` into its content, holding one element at `offset` in
 * that content - laid out the way a browser would report it. The page column
 * around it scrolls too, which is the ancestor `scrollIntoView` would drag.
 */
function layout({
  scrollTop,
  offset,
  height = 100,
}: {
  scrollTop: number;
  offset: number;
  height?: number;
}) {
  const viewTop = 100;
  const page = document.createElement("div");
  page.style.overflowY = "auto";
  page.scrollTo = vi.fn() as unknown as typeof page.scrollTo;
  const scroller = document.createElement("div");
  scroller.style.overflowY = "auto";
  Object.defineProperty(scroller, "scrollTop", { get: () => scrollTop });
  Object.defineProperty(scroller, "clientHeight", { get: () => 400 });
  scroller.getBoundingClientRect = () => ({ top: viewTop }) as DOMRect;
  scroller.scrollTo = vi.fn() as unknown as typeof scroller.scrollTo;
  // A wrapper that does not scroll, between the element and its scroller.
  const wrapper = document.createElement("div");
  const target = document.createElement("section");
  const top = viewTop + offset - scrollTop;
  target.getBoundingClientRect = () => ({ top, bottom: top + height, height }) as DOMRect;
  target.scrollIntoView = vi.fn();
  wrapper.append(target);
  scroller.append(wrapper);
  page.append(scroller);
  document.body.append(page);
  return { page, scroller, target };
}

describe("scrollWithin", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("moves only the nearest scroller, never the page around it", () => {
    const { page, scroller, target } = layout({ scrollTop: 0, offset: 1000 });
    scrollWithin(target, "start", "smooth");
    expect(scroller.scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: "smooth" });
    expect(page.scrollTo).not.toHaveBeenCalled();
    expect(target.scrollIntoView).not.toHaveBeenCalled();
  });

  it("puts the element at the top of the scroller", () => {
    const { scroller, target } = layout({ scrollTop: 50, offset: 300 });
    scrollWithin(target, "start", "auto");
    expect(scroller.scrollTo).toHaveBeenCalledWith({ top: 300, behavior: "auto" });
  });

  it("centres the element in the scroller", () => {
    const { scroller, target } = layout({ scrollTop: 0, offset: 1000 });
    scrollWithin(target, "center", "smooth");
    // 1000 into the content, less half of the 300px left around a 100px card.
    expect(scroller.scrollTo).toHaveBeenCalledWith({ top: 850, behavior: "smooth" });
  });

  it("leaves an element already in full view where it is", () => {
    const { scroller, target } = layout({ scrollTop: 0, offset: 200 });
    scrollWithin(target, "nearest", "auto");
    expect(scroller.scrollTo).not.toHaveBeenCalled();
  });

  it("brings an element below the fold up just far enough to show all of it", () => {
    const { scroller, target } = layout({ scrollTop: 0, offset: 1000 });
    scrollWithin(target, "nearest", "auto");
    // Its bottom, 1100 into the content, at the scroller's 400px bottom edge.
    expect(scroller.scrollTo).toHaveBeenCalledWith({ top: 700, behavior: "auto" });
  });

  it("brings an element above the fold down to the top", () => {
    const { scroller, target } = layout({ scrollTop: 900, offset: 600 });
    scrollWithin(target, "nearest", "auto");
    expect(scroller.scrollTo).toHaveBeenCalledWith({ top: 600, behavior: "auto" });
  });

  it("shows the top of an element taller than the scroller", () => {
    const { scroller, target } = layout({ scrollTop: 0, offset: 1000, height: 600 });
    scrollWithin(target, "nearest", "auto");
    expect(scroller.scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: "auto" });
  });

  it("does nothing for an element no scroller holds", () => {
    const target = document.createElement("section");
    target.scrollIntoView = vi.fn();
    document.body.append(target);
    expect(() => scrollWithin(target, "center", "auto")).not.toThrow();
    expect(target.scrollIntoView).not.toHaveBeenCalled();
  });
});
