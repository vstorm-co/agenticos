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

  it("leaves long pages unconstrained so main's bottom padding lands after the content", () => {
    expect(rootClasses("/en/agents")).not.toContain("min-h-0");
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
