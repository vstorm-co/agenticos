import { act, cleanup, render } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

describe("pointAt", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    useMotionStore.setState({ motion: "system" });
    // Unmount what a test rendered before wiping what it wrote by hand, or the
    // popover's portal is removed from under React.
    cleanup();
    document.body.innerHTML = "";
  });

  it("rings a control that is on the page, then lets it go", async () => {
    document.body.innerHTML = `<button data-tour="agents-new">New</button>`;
    const button = document.querySelector("button")!;

    await expect(pointAt("agents-new")).resolves.toBe(true);
    expect(button).toHaveClass("assistant-highlight");

    vi.advanceTimersByTime(3000);
    expect(button).not.toHaveClass("assistant-highlight");
  });

  it("switches the tab a control lives behind, as the walkthrough does", async () => {
    // The Builder's tabs are controlled from the URL; a controlled pair is the
    // same shape. `agent-instructions` is on the Build tab in the tour registry.
    function Builder() {
      const [tab, setTab] = useState("limits");
      return (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="build" data-tour="agent-tab-build">
              Build
            </TabsTrigger>
            <TabsTrigger value="limits">Limits</TabsTrigger>
          </TabsList>
          <TabsContent value="build">
            <div data-tour="agent-instructions">instructions</div>
          </TabsContent>
          <TabsContent value="limits">limits-panel</TabsContent>
        </Tabs>
      );
    }
    render(<Builder />);
    const build = document.querySelector('[data-tour="agent-tab-build"]')!;
    expect(build).toHaveAttribute("data-state", "inactive");

    // Inside `act`: the first poll activates the trigger synchronously.
    let pointing: Promise<boolean> = Promise.resolve(false);
    await act(async () => {
      pointing = pointAt("agent-instructions");
      await vi.advanceTimersByTimeAsync(200);
    });

    // Settled within two polls - a pointer still waiting has not found it.
    await expect(Promise.race([pointing, Promise.resolve("waiting")])).resolves.toBe(true);
    expect(build).toHaveAttribute("data-state", "active");
    expect(document.querySelector('[data-tour="agent-instructions"]')).toHaveClass(
      "assistant-highlight",
    );
  });

  it("opens the popover a control lives behind", async () => {
    // `chat-approval-mode` sits inside the chat settings popover.
    render(
      <Popover>
        <PopoverTrigger data-tour="chat-settings">Settings</PopoverTrigger>
        <PopoverContent>
          <div data-tour="chat-approval-mode">approval</div>
        </PopoverContent>
      </Popover>,
    );

    // Inside `act`: the first poll activates the trigger synchronously.
    let pointing: Promise<boolean> = Promise.resolve(false);
    await act(async () => {
      pointing = pointAt("chat-approval-mode");
      await vi.advanceTimersByTimeAsync(200);
    });

    // Settled within two polls - a pointer still waiting has not found it.
    await expect(Promise.race([pointing, Promise.resolve("waiting")])).resolves.toBe(true);
    expect(document.querySelector('[data-tour="chat-approval-mode"]')).toHaveClass(
      "assistant-highlight",
    );
  });

  it("jumps rather than glides for a reader who asked for less motion", async () => {
    useMotionStore.setState({ motion: "reduce" });
    document.body.innerHTML = `<button data-tour="agents-new">New</button>`;
    const scroll = vi.spyOn(document.querySelector("button")!, "scrollIntoView");

    await expect(pointAt("agents-new")).resolves.toBe(true);
    expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "auto" });
  });

  it("gives up on a control the page never draws", async () => {
    const pointing = pointAt("agent-instructions");
    await vi.advanceTimersByTimeAsync(5000);

    await expect(pointing).resolves.toBe(false);
  });
});
