import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PageTransition } from "./page-transition";

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
    const classes = rootClasses("/en/agents");

    expect(classes).toContain("pb-[calc(5rem+env(safe-area-inset-bottom))]");
    expect(classes).toContain("lg:pb-16");
  });

  it("counts the safe-area inset rather than assuming it away", () => {
    // The mobile tab bar is `min-h-[56px]` plus `env(safe-area-inset-bottom)`,
    // and `viewportFit: "cover"` makes that inset 34px on a modern iPhone - so
    // a flat 80px leaves the last 10px of the page under the bar.
    expect(rootClasses("/en/agents")).toContain("env(safe-area-inset-bottom)");
  });

  it("leaves the chat without it, so the composer sits on the bottom edge", () => {
    // Room under a fixed control is a gap under it.
    expect(rootClasses("/en/chat")).not.toContain("pb-");
  });

  it("constrains Activity too, where the list and the run detail scroll apart", () => {
    // Two columns, each with its own scroll: the table keeps its column headers
    // and the run detail keeps its own header, which is only true while neither
    // of them is scrolling the page.
    expect(rootClasses("/en/runs")).toContain("min-h-0");
  });

  it("does not mistake a route that merely starts with a constrained one", () => {
    expect(rootClasses("/en/chatty")).not.toContain("min-h-0");
    expect(rootClasses("/en/runsomething")).not.toContain("min-h-0");
  });
});
