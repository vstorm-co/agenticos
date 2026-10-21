import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  FINISH_MS,
  GIVE_UP_MS,
  NavigationProgress,
  SHOW_AFTER_MS,
  navigationTarget,
} from "./navigation-progress";

const place = vi.hoisted(() => ({ path: "/chat", search: "" }));

vi.mock("next/navigation", () => ({
  usePathname: () => place.path,
  useSearchParams: () => new URLSearchParams(place.search),
  // next-intl's createNavigation wraps these at module scope; see `vitest.setup.ts`.
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

/** A link in the page, clicked as a person would. */
function link(href: string, attrs: Record<string, string> = {}): HTMLAnchorElement {
  const anchor = document.createElement("a");
  anchor.href = href;
  for (const [name, value] of Object.entries(attrs)) anchor.setAttribute(name, value);
  anchor.append(document.createElement("span"));
  document.body.append(anchor);
  // jsdom would try to navigate; `next/link` prevents the default too.
  anchor.addEventListener("click", (event) => event.preventDefault());
  return anchor;
}

const bar = () => screen.queryByRole("progressbar", { name: "Opening the page" });

beforeEach(() => {
  place.path = "/chat";
  place.search = "";
  window.history.replaceState({}, "", "/chat");
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

describe("NavigationProgress", () => {
  it("shows once a navigation takes longer than a blink, and finishes when the page arrives", () => {
    const { rerender } = render(<NavigationProgress />);
    fireEvent.click(link("/dashboard").firstElementChild!);
    expect(bar()).toBeNull();

    act(() => vi.advanceTimersByTime(SHOW_AFTER_MS));
    expect(bar()).toHaveAttribute("data-phase", "pending");

    place.path = "/dashboard";
    rerender(<NavigationProgress />);
    expect(bar()).toHaveAttribute("data-phase", "done");
    act(() => vi.advanceTimersByTime(FINISH_MS));
    expect(bar()).toBeNull();
  });

  it("shows nothing for a navigation that arrives at once", () => {
    const { rerender } = render(<NavigationProgress />);
    fireEvent.click(link("/dashboard"));
    place.path = "/dashboard";
    rerender(<NavigationProgress />);
    act(() => vi.advanceTimersByTime(GIVE_UP_MS));
    expect(bar()).toBeNull();
  });

  it("keeps waiting on the page it left when a second link is clicked on the way", () => {
    const { rerender } = render(<NavigationProgress />);
    fireEvent.click(link("/dashboard"));
    act(() => vi.advanceTimersByTime(SHOW_AFTER_MS));
    fireEvent.click(link("/agents"));
    act(() => vi.advanceTimersByTime(SHOW_AFTER_MS));
    expect(bar()).toHaveAttribute("data-phase", "pending");
    place.path = "/agents";
    rerender(<NavigationProgress />);
    expect(bar()).toHaveAttribute("data-phase", "done");
  });

  it("lets go of a navigation that never arrives", () => {
    render(<NavigationProgress />);
    fireEvent.click(link("/dashboard"));
    act(() => vi.advanceTimersByTime(SHOW_AFTER_MS));
    expect(bar()).not.toBeNull();
    act(() => vi.advanceTimersByTime(GIVE_UP_MS));
    expect(bar()).toBeNull();
  });

  it("counts a change of the search as arriving", () => {
    const { rerender } = render(<NavigationProgress />);
    fireEvent.click(link("/chat?tab=files"));
    act(() => vi.advanceTimersByTime(SHOW_AFTER_MS));
    place.search = "tab=files";
    rerender(<NavigationProgress />);
    expect(bar()).toHaveAttribute("data-phase", "done");
  });

  it("stays out of a click that opens nothing", () => {
    render(<NavigationProgress />);
    fireEvent.click(link("/dashboard", { target: "_blank" }));
    fireEvent.click(document.body);
    act(() => vi.advanceTimersByTime(SHOW_AFTER_MS));
    expect(bar()).toBeNull();
  });

  it("stops listening when it unmounts", () => {
    const { unmount } = render(<NavigationProgress />);
    unmount();
    fireEvent.click(link("/dashboard"));
    act(() => vi.advanceTimersByTime(SHOW_AFTER_MS));
    expect(bar()).toBeNull();
  });
});

describe("navigationTarget", () => {
  const clickOn = (target: EventTarget, init: MouseEventInit = {}) => {
    const event = new MouseEvent("click", { bubbles: true, button: 0, ...init });
    Object.defineProperty(event, "target", { value: target });
    return navigationTarget(event);
  };

  it("follows a plain click on a link to another page of the console", () => {
    expect(clickOn(link("/dashboard"))?.pathname).toBe("/dashboard");
  });

  it.each([
    ["a middle click", { button: 1 }],
    ["a click with Cmd", { metaKey: true }],
    ["a click with Ctrl", { ctrlKey: true }],
    ["a click with Shift", { shiftKey: true }],
    ["a click with Alt", { altKey: true }],
  ])("leaves %s to the browser", (_, init) => {
    expect(clickOn(link("/dashboard"), init)).toBeNull();
  });

  it.each([
    ["a new tab", "/dashboard", { target: "_blank" }],
    ["a download", "/files/report.csv", { download: "" }],
    ["another site", "https://example.com/", {}],
    ["the page already open", "/chat", {}],
    ["a jump within the page", "/chat#composer", {}],
  ])("ignores a link to %s", (_, href, attrs) => {
    expect(clickOn(link(href, attrs))).toBeNull();
  });

  it("follows a link that names its own frame", () => {
    expect(clickOn(link("/dashboard", { target: "_self" }))).not.toBeNull();
  });

  it("ignores a click on anything that is not a link", () => {
    expect(clickOn(document.body)).toBeNull();
    expect(clickOn(window)).toBeNull();
  });
});
