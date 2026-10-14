import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DiscoverTips } from "./discover-tips";

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
    expect(screen.getAllByRole("article")).toHaveLength(9);
  });

  it("leaves out what the reader cannot use", () => {
    data.perms = new Set();
    render(<DiscoverTips />);

    // Only the MCP tip needs nothing: every member can connect their own client.
    expect(screen.getAllByRole("article")).toHaveLength(1);
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
    expect(screen.getAllByRole("article")).toHaveLength(8);
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

    expect(screen.getAllByRole("article")).toHaveLength(9);
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

  it("draws in the Toolbox style the reader picked", () => {
    window.localStorage.setItem("capability-view", "crew");
    const { container } = render(<DiscoverTips />);

    expect(container.querySelector(".v-F")).not.toBeNull();
    expect(container.querySelector(".v-B")).toBeNull();
  });
});
