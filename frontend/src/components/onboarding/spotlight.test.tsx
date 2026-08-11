import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { activateTab, pulse, spotlightPath, waitForElement } from "./spotlight";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";

describe("activateTab", () => {
  it("switches a Radix tab that a bare click leaves unmoved", () => {
    render(
      <Tabs defaultValue="build">
        <TabsList>
          <TabsTrigger value="build">Build</TabsTrigger>
          <TabsTrigger value="toolbox">Toolbox</TabsTrigger>
        </TabsList>
        <TabsContent value="build">build-panel</TabsContent>
        <TabsContent value="toolbox">toolbox-panel</TabsContent>
      </Tabs>,
    );

    const toolbox = screen.getByRole("tab", { name: "Toolbox" });

    // The bug the tour hit: a bare click does not activate a Radix tab, so the
    // panel — and any spotlight target inside it — never mounts.
    act(() => toolbox.click());
    expect(screen.queryByText("toolbox-panel")).toBeNull();

    // activateTab fires what Radix actually listens to, so the panel mounts.
    act(() => activateTab(toolbox));
    expect(screen.getByText("toolbox-panel")).toBeInTheDocument();
  });
});

describe("spotlightPath", () => {
  it("cuts a hole into a full-viewport rectangle", () => {
    const d = spotlightPath(1000, 800, 100, 100, 200, 50, 12);
    // The outer subpath is the whole viewport...
    expect(d.startsWith("M1000,0 L0,0 L0,800 L1000,800 L1000,0 Z")).toBe(true);
    // ...and the inner subpath opens at the hole's top-left plus the corner radius.
    expect(d).toContain("M112,100");
    expect(d.endsWith("z")).toBe(true);
  });

  it("clamps the corner radius so a control smaller than it never inverts the arcs", () => {
    // r wants 12 but the hole is 10×10, so it is clamped to half the shorter side.
    const d = spotlightPath(1000, 800, 0, 0, 10, 10, 12);
    expect(d).toContain("M5,0");
    // across = 10 - 2*5 = 0: the straight runs collapse, the arcs meet.
    expect(d).toContain("h0");
  });
});

describe("pulse", () => {
  it("plays the click flourish for the hold, then clears it", async () => {
    const element = document.createElement("button");
    const controller = new AbortController();

    const done = pulse(element, controller.signal, 5);
    // The class is on for the whole hold so the CSS animation runs...
    expect(element.classList.contains("tour-click-pulse")).toBe(true);

    await done;
    // ...and off afterwards, so re-highlighting the same element replays it.
    expect(element.classList.contains("tour-click-pulse")).toBe(false);
  });

  it("clears the flourish at once when the wait is aborted", async () => {
    const element = document.createElement("button");
    const controller = new AbortController();
    controller.abort();

    // A reader who moves on mid-pulse must not leave the class stuck on.
    await pulse(element, controller.signal, 10_000);
    expect(element.classList.contains("tour-click-pulse")).toBe(false);
  });
});

describe("waitForElement", () => {
  it("with no timeout, waits for a target that mounts late rather than giving up", async () => {
    const controller = new AbortController();
    const pending = waitForElement('[data-tour="late"]', controller.signal, null);

    const el = document.createElement("div");
    el.setAttribute("data-tour", "late");
    document.body.appendChild(el);

    expect(await pending).toBe(el);
    el.remove();
  });

  it("with no timeout, still ends when the wait is aborted", async () => {
    const controller = new AbortController();
    const pending = waitForElement('[data-tour="never"]', controller.signal, null);
    controller.abort();

    expect(await pending).toBeNull();
  });
});
