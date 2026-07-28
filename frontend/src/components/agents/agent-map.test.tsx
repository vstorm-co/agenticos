import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { AgentMap, MAP_ICONS, type MapNode } from "./agent-map";

function node(overrides: Partial<MapNode> = {}): MapNode {
  return {
    key: "skills",
    title: "Skills",
    icon: MAP_ICONS.skills,
    items: ["refund-policy"],
    empty: "No skills attached",
    side: "out",
    ...overrides,
  };
}

describe("AgentMap", () => {
  it("says what is attached, by name", () => {
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node()]} />);

    expect(
      within(screen.getByRole("group", { name: "Skills" })).getByText("refund-policy"),
    ).toBeInTheDocument();
  });

  it("names an empty box rather than hiding it", () => {
    // The whole reason to open the map before publishing: the thing nobody
    // attached is invisible in a column of collapsed forms.
    render(<AgentMap agentName="Support" instructions="Be brief." nodes={[node({ items: [] })]} />);

    expect(screen.getByText("No skills attached")).toBeInTheDocument();
  });

  it("says an agent has no instructions instead of drawing an empty panel", () => {
    // A blank centre reads as a rendering failure, and "no instructions" is a
    // finding — that agent answers as whatever the model felt like.
    render(<AgentMap agentName="Support" instructions="   " nodes={[]} />);

    expect(screen.getByText("No instructions written")).toBeInTheDocument();
  });
});
