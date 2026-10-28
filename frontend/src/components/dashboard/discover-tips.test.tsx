import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ADVANCE_MS, DiscoverTips } from "./discover-tips";

const data = vi.hoisted(() => ({ perms: new Set<string>() }));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (perm: string) => data.perms.has(perm) }),
}));

const EVERYTHING = ["agents:edit", "artifacts:view", "channels:manage"];

beforeEach(() => {
  window.localStorage.clear();
  data.perms = new Set(EVERYTHING);
});

afterEach(() => {
  vi.restoreAllMocks();
});

const tile = (name: string) => screen.getByRole("article", { name });

describe("the dashboard's discover tips", () => {
  it("offers each feature with a way to it", () => {
    render(<DiscoverTips />);

    expect(screen.getByRole("heading", { name: "Discover AgenticOS" })).toBeInTheDocument();
    expect(
      within(tile("Use it from Claude Code or Cursor")).getByRole("link", {
        name: /Connect an app/,
      }),
    ).toHaveAttribute("href", "/settings/mcp");
    expect(within(tile("Turn answers into apps")).getByRole("link")).toHaveAttribute(
      "href",
      "/apps",
    );
    expect(within(tile("Point the agent with @")).getByRole("link")).toHaveAttribute(
      "href",
      "/chat",
    );
    expect(within(tile("Shortcuts with /")).getByText("/")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(11);
    expect(screen.getAllByRole("article")[0]).toHaveAccessibleName(/computer/i);
  });

  it("leaves out what the reader cannot use", () => {
    data.perms = new Set();
    render(<DiscoverTips />);

    // What needs nothing: the chat's two keys, and connecting one's own client.
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });

  it("closes one tip, and remembers it", async () => {
    const { unmount } = render(<DiscoverTips />);

    await userEvent.click(
      screen.getByRole("button", { name: "Hide the tip Turn answers into apps" }),
    );
    expect(screen.queryByRole("article", { name: "Turn answers into apps" })).toBeNull();

    unmount();
    render(<DiscoverTips />);
    expect(screen.queryByRole("article", { name: "Turn answers into apps" })).toBeNull();
    expect(screen.getAllByRole("article")).toHaveLength(10);
  });

  it("goes away once every tip is closed", async () => {
    render(<DiscoverTips />);

    await userEvent.click(screen.getByRole("button", { name: "Hide tips" }));

    expect(screen.queryByText("Discover AgenticOS")).toBeNull();
  });

  it("still closes where the browser keeps nothing", async () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    render(<DiscoverTips />);

    await userEvent.click(screen.getByRole("button", { name: "Hide tips" }));

    expect(screen.queryByText("Discover AgenticOS")).toBeNull();
  });

  it("ignores a stored value that is not a list of tips", () => {
    window.localStorage.setItem("agenticos:discover-tips:dismissed", JSON.stringify({ apps: 1 }));
    render(<DiscoverTips />);

    expect(screen.getAllByRole("article")).toHaveLength(11);
  });

  it("pages sideways from its arrows", async () => {
    const scrollBy = vi.fn();
    Element.prototype.scrollBy = scrollBy;
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
    render(<DiscoverTips />);

    await userEvent.click(screen.getByRole("button", { name: "More tips" }));
    await userEvent.click(screen.getByRole("button", { name: "Previous tips" }));

    expect(scrollBy.mock.calls.map(([options]) => options.left)).toEqual([340, -340]);
  });

  it("lights one tile at a time and moves on to the next, back to the first after the last", () => {
    vi.useFakeTimers();
    const scrollTo = vi.fn();
    Element.prototype.scrollTo = scrollTo;
    render(<DiscoverTips />);
    const lit = () =>
      screen.getAllByRole("article").findIndex((tile) => tile.dataset.lit === "true");

    expect(lit()).toBe(0);
    act(() => vi.advanceTimersByTime(ADVANCE_MS));
    expect(lit()).toBe(1);
    expect(scrollTo).toHaveBeenLastCalledWith({ left: expect.any(Number), behavior: "smooth" });

    act(() => vi.advanceTimersByTime(ADVANCE_MS * 10));
    expect(lit()).toBe(0);
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 0, behavior: "smooth" });
    vi.useRealTimers();
  });

  it("holds still while the reader is on the strip", () => {
    vi.useFakeTimers();
    Element.prototype.scrollTo = vi.fn();
    render(<DiscoverTips />);
    const strip = screen.getAllByRole("article")[0]!.parentElement!;
    const lit = () =>
      screen.getAllByRole("article").findIndex((tile) => tile.dataset.lit === "true");

    fireEvent.mouseEnter(strip);
    act(() => vi.advanceTimersByTime(ADVANCE_MS * 2));
    expect(lit()).toBe(0);
    fireEvent.mouseLeave(strip);
    fireEvent.focus(strip);
    act(() => vi.advanceTimersByTime(ADVANCE_MS * 2));
    expect(lit()).toBe(0);
    fireEvent.blur(strip);
    act(() => vi.advanceTimersByTime(ADVANCE_MS));
    expect(lit()).toBe(1);
    vi.useRealTimers();
  });

  it("does not move for a reader who asked for less motion", () => {
    vi.useFakeTimers();
    const desk = window.matchMedia;
    window.matchMedia = ((query: string) => ({ matches: true, media: query })) as never;
    render(<DiscoverTips />);
    act(() => vi.advanceTimersByTime(ADVANCE_MS * 3));
    expect(screen.getAllByRole("article").findIndex((tile) => tile.dataset.lit === "true")).toBe(0);
    window.matchMedia = desk;
    vi.useRealTimers();
  });

  it("draws its tiles in the Toolbox's isometric style", () => {
    const { container } = render(<DiscoverTips />);

    expect(container.querySelector(".v-B svg")).not.toBeNull();
  });
});
