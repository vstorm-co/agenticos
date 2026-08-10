import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { activateTab } from "./spotlight";
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
