import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CapabilityWorkbench } from "./capability-workbench";
import { jsonSchemaType } from "./capability-settings";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

vi.mock("@/hooks", () => ({ useSecrets: () => ({ secrets: [], isLoading: false, error: null }) }));

const CHARTS: CapabilityCatalogEntry = {
  id: "charts",
  name: "Charts",
  category: "analysis",
  description: "Draw a chart so the user can see the numbers rather than read them.",
  side_effecting: false,
  scopes: [],
  tools: [
    {
      id: "create_chart",
      name: "create_chart",
      description: "Draw a chart of numbers you already have, so the user can see them.",
    },
  ],
  contracts: [
    {
      tool_id: "create_chart",
      description:
        "Draw a chart of numbers you already have.\n\nFor a scatter chart, give every row a numeric x and y.",
      parameters: {
        type: "object",
        properties: {
          chart_type: { type: "string" },
          title: { type: "string" },
          series: {
            anyOf: [{ type: "array", items: { $ref: "#/$defs/ChartSeries" } }, { type: "null" }],
          },
        },
        required: ["chart_type", "title"],
      },
    },
  ],
  config_schema: null,
  requires_secret: null,
};

const SKILLS: CapabilityCatalogEntry = {
  ...CHARTS,
  id: "skills",
  name: "Skills",
  category: "knowledge",
  description: "Reusable know-how this organization has written down.",
  tools: [
    { id: "list_skills", name: "list_skills", description: "Get an overview of all skills." },
    { id: "load_skill", name: "load_skill", description: "Load one skill's instructions." },
  ],
  contracts: [],
};

function binding(
  id: string,
  overrides: Partial<CapabilityBindingSpec> = {},
): CapabilityBindingSpec {
  return {
    id,
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: true,
    ...overrides,
  };
}

function renderWorkbench(props: Partial<Parameters<typeof CapabilityWorkbench>[0]> = {}) {
  return render(
    <CapabilityWorkbench
      catalog={[CHARTS, SKILLS]}
      selected={[]}
      onToggle={vi.fn()}
      onChange={vi.fn()}
      {...props}
    />,
  );
}

describe("the capability workbench", () => {
  it("says how many tools a capability contributes before you grant it", async () => {
    // The complaint this layout exists for: the old grid showed one sentence per
    // capability and never what it actually gives the model.
    renderWorkbench();

    expect(await screen.findByText("1 tool")).toBeInTheDocument();
    expect(screen.getByText("2 tools")).toBeInTheDocument();
  });

  it("shows what a capability offers without switching it on", async () => {
    // Otherwise the only way to learn what granting it does is to grant it.
    renderWorkbench();

    await userEvent.click(screen.getByRole("button", { name: /^Skills/ }));

    expect(screen.getByText("list_skills")).toBeInTheDocument();
    expect(screen.getByText("load_skill")).toBeInTheDocument();
  });

  it("reading a capability is not granting it", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ onToggle });

    await userEvent.click(screen.getByRole("button", { name: /^Skills/ }));

    expect(onToggle).not.toHaveBeenCalled();
  });

  it("grants a capability from its checkbox", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ onToggle });

    await userEvent.click(screen.getByRole("checkbox", { name: "Give this agent Charts" }));

    expect(onToggle).toHaveBeenCalledWith("charts");
  });

  it("configures the capability it is showing, not every one that is on", async () => {
    // The pile of settings cards under the old grid is the thing being replaced:
    // five enabled capabilities produced five panels, none of them beside the
    // checkbox that created it.
    renderWorkbench({ selected: [binding("charts"), binding("skills")] });

    const panel = screen.getByRole("group", { name: "Charts" });
    expect(within(panel).getByText("charts")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Skills" })).not.toBeInTheDocument();
  });

  it("offers the whole description the model reads, not its first line", () => {
    // The description editor holds the full contract text: an override
    // replaces everything the model is told, so editing a summary-only field
    // would silently drop the rest.
    renderWorkbench({ selected: [binding("charts")] });

    expect(screen.getByLabelText("Description the model reads")).toHaveValue(
      "Draw a chart of numbers you already have.\n\nFor a scatter chart, give every row a numeric x and y.",
    );
  });

  it("names the arguments the model has to fill in", async () => {
    renderWorkbench({ selected: [binding("charts")] });

    await userEvent.click(screen.getByText("Arguments (3)"));

    expect(screen.getByText("chart_type")).toBeInTheDocument();
    // Two of the three are required, and which is which decides whether an
    // agent's rewording of the tool can leave one out.
    expect(screen.getAllByText("required")).toHaveLength(2);
  });
});

describe("jsonSchemaType", () => {
  it("reads a plain type", () => {
    expect(jsonSchemaType({ type: "string" })).toBe("string");
  });

  it("drops the null half of an optional argument", () => {
    // `T | null` is how every optional argument arrives; naming the null adds
    // nothing that the "required" marker does not already say.
    expect(jsonSchemaType({ anyOf: [{ type: "integer" }, { type: "null" }] })).toBe("integer");
  });

  it("names what an array holds", () => {
    expect(jsonSchemaType({ type: "array", items: { type: "string" } })).toBe("array<string>");
  });

  it("names a referenced model by its own name", () => {
    expect(jsonSchemaType({ $ref: "#/$defs/ChartSeries" })).toBe("ChartSeries");
  });

  it("says so rather than guessing when there is nothing to read", () => {
    expect(jsonSchemaType(undefined)).toBe("unknown");
  });
});
