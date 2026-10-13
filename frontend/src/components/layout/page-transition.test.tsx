import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PageTransition } from "./page-transition";
import { PAGE_CLEARANCE } from "@/lib/page-clearance";

let pathname = "/";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

function rootClasses(path: string): string {
  pathname = path;
  const { container } = render(
    <PageTransition>
      <div />
    </PageTransition>,
  );
  return (container.firstElementChild as HTMLElement).className;
}

describe("the page transition wrapper", () => {
  it("constrains its height on the chat route so only the message pane scrolls", () => {
    // A flex item's min-height:0 is a floor, not a ceiling: without min-h-0
    // on THIS box, the transcript's min-content height propagates up and the
    // whole page scrolls instead of the chat window.
    expect(rootClasses("/en/chat")).toContain("min-h-0");
  });

  it("leaves long pages unconstrained so the room under them lands after the content", () => {
    expect(rootClasses("/en/agents")).not.toContain("min-h-0");
  });

  it("declares the room under a page here, where it is painted", () => {
    // Not on `main`, though `main` is what scrolls: `DeploymentGate` wraps this
    // in a `min-h-0 flex-1` box, so a long page overflows that box and `main`'s
    // padding edge stays where the shorter box ended - 0px below the last card
    // at every width, measured in Chromium 151 and WebKit 26.5 (#933). This box
    // grows with its content, so padding here lands after the last element.
    expect(rootClasses("/en/agents")).toContain(PAGE_CLEARANCE);
  });

  it("counts the safe-area inset rather than assuming it away", () => {
    // The mobile tab bar is `min-h-[56px]` plus `env(safe-area-inset-bottom)`,
    // and `viewportFit: "cover"` makes that inset 34px on a modern iPhone - so
    // a flat 80px leaves the last 10px of the page under the bar.
    expect(PAGE_CLEARANCE).toContain("env(safe-area-inset-bottom)");
  });

  it("leaves the chat without it, so the composer sits on the bottom edge", () => {
    // Room under a fixed control is a gap under it.
    expect(rootClasses("/en/chat")).not.toContain("pb-");
  });

  it("does not constrain Activity, which has been an ordinary scrolling page since #914", () => {
    // The run detail is `sticky` inside the page's own scroll, not a pane with a
    // scrollbar of its own - the page's root says so (`flex flex-col`). This
    // test asserted the opposite, which was true before the page was rebuilt.
    expect(rootClasses("/en/runs")).not.toContain("min-h-0");
  });

  it("leaves Activity to place its own room, because a sticky panel is clamped to it", () => {
    // Padding on this box shortens the containing block the run detail may pin
    // in: 64px of it put the panel's top at -48px at maximum scroll and cut its
    // own header off by 56px, measured at 1440x800 in Chromium. Activity
    // declares `PAGE_CLEARANCE` on its list column instead, where it lands under
    // the last row and the row itself still ends at the viewport (#1206).
    expect(rootClasses("/en/runs")).not.toContain("pb-");
  });

  it("does not mistake a route that merely starts with a constrained one", () => {
    expect(rootClasses("/en/chatty")).not.toContain("min-h-0");
    expect(rootClasses("/en/runsomething")).not.toContain("min-h-0");
    // And it gets the room, which the prefix match would have taken away.
    expect(rootClasses("/en/runsomething")).toContain(PAGE_CLEARANCE);
  });
});
