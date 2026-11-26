import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { useMotionStore } from "@/stores/motion-store";

import { ADVANCE_MS, DiscoverTips } from "./discover-tips";

const data = vi.hoisted(() => ({ perms: new Set<string>() }));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (perm: string) => data.perms.has(perm) }),
}));

const EVERYTHING = [
  "agents:edit",
  "artifacts:view",
  "channels:manage",
  "projects:view",
  "mcp:personal:use",
];

beforeEach(() => {
  window.localStorage.clear();
  useMotionStore.setState({ motion: "system" });
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
    expect(screen.getAllByRole("article")).toHaveLength(16);
    expect(screen.getAllByRole("article")[0]).toHaveAccessibleName(
      "Bring your Claude or Codex account",
    );
    for (const [name, href] of [
      ["Bring your Claude or Codex account", "/settings/subscriptions"],
      ["Start with a real task", "/chat?new=workspace&answerer=agenticos"],
      ["Bring your everyday tools", "/mcp-servers"],
      ["Keep a project together", "/projects"],
      ["Control your personal context", "/settings/memory"],
    ] as const)
      expect(within(tile(name)).getByRole("link")).toHaveAttribute("href", href);
  });

  it("leaves out what the reader cannot use", () => {
    data.perms = new Set();
    render(<DiscoverTips />);

    expect(screen.getAllByRole("article")).toHaveLength(6);
    expect(tile("Bring your Claude or Codex account")).toBeInTheDocument();
    expect(tile("Control your personal context")).toBeInTheDocument();
    expect(
      screen.queryByRole("article", { name: "Bring your everyday tools" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("article", { name: "Keep a project together" }),
    ).not.toBeInTheDocument();
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
    expect(screen.getAllByRole("article")).toHaveLength(15);
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

    expect(screen.getAllByRole("article")).toHaveLength(16);
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

    act(() => vi.advanceTimersByTime(ADVANCE_MS * (screen.getAllByRole("article").length - 1)));
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

  it.each(["touchEnd", "touchCancel"] as const)(
    "pauses during touch and resumes after %s only once focus leaves too",
    (release) => {
      vi.useFakeTimers();
      Element.prototype.scrollTo = vi.fn();
      render(<DiscoverTips />);
      const first = screen.getAllByRole("article")[0]!;
      const strip = first.parentElement!;
      const link = within(first).getByRole("link");
      fireEvent.touchStart(strip);
      act(() => vi.advanceTimersByTime(ADVANCE_MS * 2));
      expect(first).toHaveAttribute("data-lit", "true");
      fireEvent.focus(link);
      fireEvent[release](strip);
      fireEvent.mouseEnter(strip);
      fireEvent.mouseLeave(strip);
      act(() => vi.advanceTimersByTime(ADVANCE_MS * 2));
      expect(first).toHaveAttribute("data-lit", "true");
      const nextLink = within(screen.getAllByRole("article")[1]!).getByRole("link");
      fireEvent.blur(link, { relatedTarget: nextLink });
      fireEvent.focus(nextLink);
      act(() => vi.advanceTimersByTime(ADVANCE_MS));
      expect(first).toHaveAttribute("data-lit", "true");
      fireEvent.blur(nextLink);
      act(() => vi.advanceTimersByTime(ADVANCE_MS));
      expect(screen.getAllByRole("article")[1]).toHaveAttribute("data-lit", "true");
      vi.useRealTimers();
    },
  );

  it("does not move for a reader who asked for less motion", () => {
    vi.useFakeTimers();
    useMotionStore.setState({ motion: "reduce" });
    render(<DiscoverTips />);
    act(() => vi.advanceTimersByTime(ADVANCE_MS * 3));
    expect(screen.getAllByRole("article").findIndex((tile) => tile.dataset.lit === "true")).toBe(0);
    vi.useRealTimers();
  });

  it("stops an existing carousel immediately when motion is reduced", () => {
    vi.useFakeTimers();
    Element.prototype.scrollTo = vi.fn();
    render(<DiscoverTips />);
    act(() => vi.advanceTimersByTime(ADVANCE_MS));
    expect(screen.getAllByRole("article")[1]).toHaveAttribute("data-lit", "true");
    act(() => useMotionStore.setState({ motion: "reduce" }));
    act(() => vi.advanceTimersByTime(ADVANCE_MS * 2));
    expect(screen.getAllByRole("article")[1]).toHaveAttribute("data-lit", "true");
    act(() => useMotionStore.setState({ motion: "full" }));
    act(() => vi.advanceTimersByTime(ADVANCE_MS));
    expect(screen.getAllByRole("article")[2]).toHaveAttribute("data-lit", "true");
    vi.useRealTimers();
  });

  it("draws its tiles in the Toolbox's isometric style", () => {
    const { container } = render(<DiscoverTips />);

    expect(container.querySelector(".v-B svg")).not.toBeNull();
  });
});
