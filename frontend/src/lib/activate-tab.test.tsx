import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { activateTab } from "./activate-tab";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

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

  it("can switch a tab without taking focus from where the reader is typing", () => {
    render(
      <>
        <input aria-label="Architect" />
        <Tabs defaultValue="build">
          <TabsList>
            <TabsTrigger value="build">Build</TabsTrigger>
            <TabsTrigger value="toolbox">Toolbox</TabsTrigger>
          </TabsList>
          <TabsContent value="build">build-panel</TabsContent>
          <TabsContent value="toolbox">toolbox-panel</TabsContent>
        </Tabs>
      </>,
    );
    const input = screen.getByRole("textbox", { name: "Architect" });
    input.focus();

    act(() => activateTab(screen.getByRole("tab", { name: "Toolbox" }), { moveFocus: false }));

    expect(screen.getByText("toolbox-panel")).toBeInTheDocument();
    expect(input).toHaveFocus();
  });

  it("opens a popover, which a press alone leaves closed", () => {
    render(
      <Popover>
        <PopoverTrigger>Settings</PopoverTrigger>
        <PopoverContent>approval-section</PopoverContent>
      </Popover>,
    );
    const trigger = screen.getByRole("button", { name: "Settings" });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");

    act(() => activateTab(trigger));
    expect(screen.getByText("approval-section")).toBeInTheDocument();
  });
});

describe("activateTab on a tab the tour has lit", () => {
  it("still presses a tab driver.js marked as opening its caption", () => {
    render(
      <Tabs defaultValue="cases">
        <TabsList>
          <TabsTrigger value="cases">Cases</TabsTrigger>
          <TabsTrigger value="grading">Grading</TabsTrigger>
        </TabsList>
        <TabsContent value="cases">cases-panel</TabsContent>
        <TabsContent value="grading">grading-panel</TabsContent>
      </Tabs>,
    );
    const grading = screen.getByRole("tab", { name: "Grading" });
    // What driver.js sets on the element it highlights.
    grading.setAttribute("aria-haspopup", "dialog");

    act(() => activateTab(grading));
    expect(screen.getByText("grading-panel")).toBeInTheDocument();
  });
});

describe("activateTab on a plain button", () => {
  it("clicks a wizard's step, which listens for nothing else", () => {
    const onClick = vi.fn();
    render(
      <button type="button" onClick={onClick}>
        Result
      </button>,
    );
    act(() => activateTab(screen.getByRole("button", { name: "Result" })));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
