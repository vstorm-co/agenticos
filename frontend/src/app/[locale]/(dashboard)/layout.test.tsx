import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import DashboardLayout from "./layout";

/**
 * The scroll container the whole dashboard lives in, and the one class on it
 * that is not about layout.
 *
 * `main` is positioned, and not to position anything: an absolutely positioned
 * descendant with no positioned ancestor resolves against the initial containing
 * block, and its layout overflow then inflates the *document's* scrollable rect.
 * Measured on the agent Builder before this, `documentElement.scrollHeight` read
 * 3130 against a 1290 viewport while the document could not be scrolled by a
 * pixel - and Chrome draws a scrollbar track for that, inert, with a full-height
 * thumb. Anybody whose macOS is set to show scrollbars always saw two bars side
 * by side, one of which did nothing. The offenders are the hidden inputs Radix's
 * Select renders inside a capability panel.
 *
 * `relative` rather than `contain: paint`, which fixes it equally and would also
 * make this the containing block for every `fixed` descendant - the chat's
 * sources panel and two drop overlays are `fixed` and rendered inline, so
 * containment would move them.
 *
 * Walked rather than mounted: this layout is a server component whose tree pulls
 * in the whole shell, and what is asserted is one element's class list.
 */
function find(node: unknown, id: string): ReactElement | null {
  if (node === null || typeof node !== "object") return null;
  const element = node as ReactElement<{ id?: string; children?: unknown }>;
  if (element.props?.id === id) return element;
  const children = element.props?.children;
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    const hit = find(child, id);
    if (hit !== null) return hit;
  }
  return null;
}

describe("the dashboard's scroll container", () => {
  it("is positioned, so a descendant cannot inflate the document's scroll height", () => {
    const main = find(DashboardLayout({ children: null }), "main");

    expect(main).not.toBeNull();
    expect((main?.props as { className: string }).className).toContain("relative");
  });

  it("is the only thing that scrolls, inside a shell the height of the screen", () => {
    const main = find(DashboardLayout({ children: null }), "main");

    expect((main?.props as { className: string }).className).toContain("overflow-auto");
  });

  it("declares no room under a page, because its padding edge is not where a page ends", () => {
    // `DeploymentGate` wraps every page in a `min-h-0 flex-1` box, so a long
    // page overflows that and this element's bottom padding stays buried
    // mid-content - 0px below the last card at every width. The room under a
    // page is `PageTransition`'s, where it is painted (#933).
    const className = (
      find(DashboardLayout({ children: null }), "main")?.props as {
        className: string;
      }
    ).className;

    expect(className).not.toMatch(/(^|\s|:)pb-/);
  });
});
