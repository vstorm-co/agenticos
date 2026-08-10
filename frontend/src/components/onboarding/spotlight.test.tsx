import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { activateTab, pulse } from "./spotlight";
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
