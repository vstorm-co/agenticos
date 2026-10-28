import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The Builder's tabs read their state from the URL (`useUrlState`), so the
// tabs below do too, against the address jsdom actually holds.
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { consoleLink, pointAt } from "./assistant-highlight";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useUrlState } from "@/hooks/use-url-state";
import { useMotionStore } from "@/stores/motion-store";

const ORIGIN = "https://console.example";

describe("consoleLink", () => {
  it("reads a console page and the control to point at", () => {
    expect(consoleLink("/agents?highlight=agents-new", ORIGIN)).toEqual({
      path: "/agents",
      anchor: "agents-new",
    });
    expect(consoleLink("/runs?tab=spend#top", ORIGIN)).toEqual({
      path: "/runs?tab=spend#top",
      anchor: null,
    });
  });

  it("leaves every other link an ordinary link", () => {
    for (const href of [
      null,
      "https://evil.example/agents",
      "//evil.example",
      "#cite-1",
      "/api/v1/agents",
    ]) {
      expect(consoleLink(href, ORIGIN)).toBeNull();
    }
  });
});

/** An agent's Builder, wired as the page wires it: the tab is `?tab=`, Build by default. */
function Builder({ agent }: { agent: string }) {
  const [tabParam, changeTab] = useUrlState("tab");
  const tab = tabParam ?? "build";
  return (
    <Tabs value={tab} onValueChange={(next) => changeTab(next === "build" ? null : next)}>
      <TabsList>
        <TabsTrigger value="build" data-tour="agent-tab-build">
          Build
        </TabsTrigger>
        <TabsTrigger value="limits" data-tour="agent-tab-limits">
          Limits
        </TabsTrigger>
      </TabsList>
      <TabsContent value="build">
        <div data-tour="agent-instructions">{agent}</div>
      </TabsContent>
      <TabsContent value="limits">
        <div data-tour="agent-limits">{agent}</div>
      </TabsContent>
    </Tabs>
  );
}

const ringed = (anchor: string) =>
  document.querySelector(`[data-tour="${anchor}"]`)?.classList.contains("assistant-highlight");

describe("pointAt", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    useMotionStore.setState({ motion: "system" });
    // Unmount what a test rendered before wiping what it wrote by hand, or the
    // popover's portal is removed from under React.
    cleanup();
    document.body.innerHTML = "";
    window.history.replaceState(null, "", "/");
  });

  /**
   * Start pointing, then run two polls inside `act`, which the tab switch needs.
   * Wrapped in an object: an async function returning the promise would await it.
   */
  async function pointFor(anchor: string, page: string): Promise<{ pointing: Promise<boolean> }> {
    let pointing: Promise<boolean> = Promise.resolve(false);
    await act(async () => {
      pointing = pointAt(anchor, page);
      await vi.advanceTimersByTimeAsync(200);
    });
    return { pointing };
  }

  /** Whether `pointing` has settled, and how - "waiting" while it still polls. */
  const settled = (pointing: Promise<boolean>) =>
    Promise.race([pointing, Promise.resolve("waiting" as const)]);

  it("rings a control that is on the page, then lets it go", async () => {
    // The router may have prefixed the locale; the page is the same page.
    window.history.replaceState(null, "", "/pl/agents");
    document.body.innerHTML = `<button data-tour="agents-new">New</button>`;
    const button = document.querySelector("button")!;

    await expect(pointAt("agents-new", "/agents")).resolves.toBe(true);
    expect(button).toHaveClass("assistant-highlight");

    vi.advanceTimersByTime(3000);
    expect(button).not.toHaveClass("assistant-highlight");
  });

  it("switches the tab a control lives behind, and leaves focus where it was", async () => {
    window.history.replaceState(null, "", "/agents/x?tab=limits");
    render(
      <>
        <input aria-label="Architect" />
        <Builder agent="x" />
      </>,
    );
    const input = document.querySelector("input")!;
    input.focus();
    const build = document.querySelector('[data-tour="agent-tab-build"]')!;
    expect(build).toHaveAttribute("data-state", "inactive");

    const { pointing } = await pointFor("agent-instructions", "/agents/x");

    await expect(settled(pointing)).resolves.toBe(true);
    expect(build).toHaveAttribute("data-state", "active");
    expect(window.location.search).toBe("");
    expect(ringed("agent-instructions")).toBe(true);
    // The reader was typing to the Architect, and still is.
    expect(document.activeElement).toBe(input);
  });

  it("leaves the page being left alone and points on the page it opens", async () => {
    // On agent x's Builder, following a link to agent y's limits. Both pages
    // carry the same tab trigger and the same anchor.
    window.history.replaceState(null, "", "/agents/x");
    const view = render(<Builder agent="x" key="x" />);

    // Outside `act`: nothing on the page may change while the pointer waits.
    const pointing = pointAt("agent-limits", "/agents/y");
    await vi.advanceTimersByTimeAsync(200);

    // Switching x's tab would rewrite its URL and cancel the navigation.
    await expect(settled(pointing)).resolves.toBe("waiting");
    expect(window.location.pathname).toBe("/agents/x");
    expect(window.location.search).toBe("");
    expect(document.querySelector('[data-tour="agent-tab-limits"]')).toHaveAttribute(
      "data-state",
      "inactive",
    );

    // The navigation lands.
    window.history.pushState(null, "", "/agents/y");
    view.rerender(<Builder agent="y" key="y" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    await expect(settled(pointing)).resolves.toBe(true);
    expect(window.location.search).toBe("?tab=limits");
    expect(document.querySelector('[data-tour="agent-limits"]')).toHaveTextContent("y");
    expect(ringed("agent-limits")).toBe(true);
  });

  it("opens the popover a control lives behind", async () => {
    // `chat-approval-mode` sits inside the chat settings popover.
    window.history.replaceState(null, "", "/chat");
    render(
      <Popover>
        <PopoverTrigger data-tour="chat-settings">Settings</PopoverTrigger>
        <PopoverContent>
          <div data-tour="chat-approval-mode">approval</div>
        </PopoverContent>
      </Popover>,
    );

    const { pointing } = await pointFor("chat-approval-mode", "/chat");

    await expect(settled(pointing)).resolves.toBe(true);
    expect(ringed("chat-approval-mode")).toBe(true);
  });

  it("jumps rather than glides for a reader who asked for less motion", async () => {
    useMotionStore.setState({ motion: "reduce" });
    document.body.innerHTML = `<button data-tour="agents-new">New</button>`;
    const scroll = vi.spyOn(document.querySelector("button")!, "scrollIntoView");

    await expect(pointAt("agents-new", "/")).resolves.toBe(true);
    expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "auto" });
  });

  it("gives up on a control the page never draws", async () => {
    const pointing = pointAt("agent-instructions", "/");
    await vi.advanceTimersByTimeAsync(5000);

    await expect(pointing).resolves.toBe(false);
  });
});
