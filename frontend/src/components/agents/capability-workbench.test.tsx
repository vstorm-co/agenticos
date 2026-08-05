import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CapabilityWorkbench } from "./capability-workbench";
import { jsonSchemaType } from "./capability-settings";
import { newSpecialist } from "@/lib/agent-spec";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

vi.mock("@/hooks", () => ({
  useSecrets: () => ({ secrets: [], isLoading: false, error: null }),
  // The workspace section reads both: where sandboxes may run, and what the
  // chosen host allows. Neither is this file's subject - `workspace-section`
  // covers them - so both answer empty, which is a deployment that registered
  // no connection.
  useSandboxConnections: () => ({ connections: [], isLoading: false, error: null }),
  useSandboxPolicy: () => ({ policy: null, isLoading: false, error: null }),
  // Delegation's panel reads the agent listing, the caller's permissions and a
  // delegate's history; the specialist editor below it reads three catalogs.
  // None of them is this file's subject - `subagents-section` covers them.
  useAgents: () => ({
    agents: [],
    total: 0,
    isLoading: false,
    promote: { mutate: vi.fn(), isPending: false },
  }),
  usePermissions: () => ({ can: () => true, isLoading: false }),
  useAgentVersions: () => ({ versions: [], isLoading: false }),
  useModelProviders: () => ({ catalog: [], profiles: [], isLoading: false }),
  useKnowledgeBases: () => ({ kbs: [], isLoading: false }),
  useSkills: () => ({ skills: [], total: 0, isLoading: false }),
  useProviderModels: () => ({ models: [], source: null, isLoading: false }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
}));

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
      subagents={[]}
      onSubagentsChange={vi.fn()}
      modelProfileId={null}
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

  it("shows an ungranted capability at full detail, not an abridgement", async () => {
    // The whole point of dropping the second, smaller rendering: the way to find
    // out what granting a capability involves used to be to grant it. Approval,
    // the editable description and the argument list are what that rendering
    // left out, so they are what this asserts.
    renderWorkbench();

    await userEvent.click(screen.getByRole("button", { name: /^Charts/ }));

    expect(screen.getByLabelText("Human approval")).toBeInTheDocument();
    expect(screen.getByLabelText("Description the model reads")).toHaveValue(
      "Draw a chart of numbers you already have.\n\nFor a scatter chart, give every row a numeric x and y.",
    );
    expect(screen.getByText("Arguments (3)")).toBeInTheDocument();
  });

  it("leaves the settings of an ungranted capability inert", async () => {
    // Reading is still not granting. Live controls writing into a binding that
    // does not exist would make opening a capability configure it by accident.
    renderWorkbench();

    await userEvent.click(screen.getByRole("button", { name: /^Charts/ }));

    expect(screen.getByLabelText("Description the model reads")).toBeDisabled();
  });

  it("grants the capability on show from the panel, not only from the list", async () => {
    // The list scrolls on its own, so the capability being read can be off
    // screen from the row that grants it.
    const onToggle = vi.fn();
    renderWorkbench({ onToggle });

    await userEvent.click(screen.getByRole("switch", { name: "Charts enabled" }));

    expect(onToggle).toHaveBeenCalledWith("charts");
  });

  it("reading a capability is not granting it", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ onToggle });

    await userEvent.click(screen.getByRole("button", { name: /^Skills/ }));

    expect(onToggle).not.toHaveBeenCalled();
  });

  it("grants a capability from its switch", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ onToggle });

    await userEvent.click(screen.getByRole("switch", { name: "Give this agent Charts" }));

    expect(onToggle).toHaveBeenCalledWith("charts");
  });

  it("configures the capability it is showing, not every one that is on", async () => {
    // The pile of settings cards under the old grid is the thing being replaced:
    // five enabled capabilities produced five panels, none of them beside the
    // switch that created it.
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

describe("the frame the two panes sit in", () => {
  it("is one height whichever capability is showing", () => {
    // The page used to be as tall as whatever was selected: opening the
    // workspace - the tallest panel by far - and then clicking a short one left
    // the document scrolled past its own content, with hundreds of pixels of
    // nothing below the section beneath it.
    const { container } = render(
      <CapabilityWorkbench
        catalog={[CHARTS]}
        selected={[]}
        onToggle={vi.fn()}
        onChange={vi.fn()}
        subagents={[]}
        onSubagentsChange={vi.fn()}
        modelProfileId={null}
      />,
    );

    expect(container.querySelector(".grid")?.className).toContain("lg:h-[36rem]");
  });

  it("scrolls each pane rather than the page", () => {
    const { container } = render(
      <CapabilityWorkbench
        catalog={[CHARTS]}
        selected={[]}
        onToggle={vi.fn()}
        onChange={vi.fn()}
        subagents={[]}
        onSubagentsChange={vi.fn()}
        modelProfileId={null}
      />,
    );

    expect(container.querySelectorAll('[class*="overflow-y-auto"]').length).toBe(2);
  });
});

describe("jsonSchemaType", () => {
  it("searches the tools too, because that is what somebody is looking for", async () => {
    // Nobody knows which capability owns `create_chart`, and the search box only
    // appears once the list is long enough that scrolling it is worse.
    const filler = Array.from({ length: 8 }, (_, index) => ({
      ...SKILLS,
      id: `filler-${index}`,
      name: `Filler ${index}`,
      category: "other",
      tools: [],
    }));
    renderWorkbench({ catalog: [CHARTS, ...filler] });

    await userEvent.type(screen.getByLabelText("Search capabilities…"), "create_chart");

    expect(screen.getByRole("button", { name: /^Charts/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Filler 0/ })).toBeNull();
  });

  it("says nothing matched rather than showing an empty column", async () => {
    const filler = Array.from({ length: 8 }, (_, index) => ({
      ...SKILLS,
      id: `filler-${index}`,
      name: `Filler ${index}`,
    }));
    renderWorkbench({ catalog: [CHARTS, ...filler] });

    await userEvent.type(screen.getByLabelText("Search capabilities…"), "zzz");

    expect(screen.getByText(/No capability or tool matches/)).toBeInTheDocument();
  });

  it("says a capability with no tools changes how the agent runs", async () => {
    // A blank line under the name would read as a capability that does nothing.
    renderWorkbench({ catalog: [{ ...CHARTS, tools: [], contracts: [] }] });

    expect(await screen.findByText("no tools - changes how it runs")).toBeInTheDocument();
  });

  it("marks a capability that acts on the world", async () => {
    // The one fact that decides whether it needs an approval policy.
    renderWorkbench({ catalog: [{ ...CHARTS, side_effecting: true }] });

    expect(await screen.findByLabelText("acts on the world")).toBeInTheDocument();
  });

  it("renders nothing at all when the deployment has no capabilities", () => {
    // Which happens while the catalog is still being fetched; an empty two-column
    // grid with a search box reads as a broken panel.
    const { container } = renderWorkbench({ catalog: [] });

    expect(container).toBeEmptyDOMElement();
  });

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

  it("lists what an enum accepts, because that is the whole type", () => {
    expect(jsonSchemaType({ enum: ["bar", "line", "scatter"] })).toBe("bar | line | scatter");
  });

  it("calls an unlabelled object an object", () => {
    expect(jsonSchemaType({})).toBe("object");
  });

  it("says so rather than guessing when there is nothing to read", () => {
    expect(jsonSchemaType(undefined)).toBe("unknown");
  });
});

describe("the workspace, which is a row like the rest and a detail unlike it", () => {
  const SANDBOX: CapabilityCatalogEntry = {
    ...CHARTS,
    id: "sandbox",
    name: "Files & shell",
    description: "Read, write and run things in a workspace that persists between turns.",
    side_effecting: true,
    scopes: ["sandbox:execute"],
    tools: [
      { id: "read_file", name: "read_file", description: "Read a file from the workspace." },
      { id: "execute", name: "execute", description: "Run a shell command in the workspace." },
    ],
    contracts: [],
    config_schema: {
      type: "object",
      properties: { backend: { type: "string", enum: ["state", "service"] } },
    },
  };

  function renderSandbox(selected: CapabilityBindingSpec[] = []) {
    return render(
      <CapabilityWorkbench
        catalog={[SANDBOX, CHARTS]}
        selected={selected}
        onToggle={vi.fn()}
        onChange={vi.fn()}
        subagents={[]}
        onSubagentsChange={vi.fn()}
        modelProfileId={null}
      />,
    );
  }

  it("says what the workspace gives the agent, not how many tools it has", async () => {
    // "2 tools" is the least useful thing to say about it in a list; whether
    // there is a shell is what somebody is scanning for. *Where* it runs is on
    // the connection rather than the spec, so the row does not claim to know.
    renderSandbox([binding("sandbox", { config: { backend: "service" } })]);

    expect(await screen.findByText("files and a shell")).toBeInTheDocument();
  });

  it("says so when the agent has no workspace at all", async () => {
    renderSandbox();

    expect(await screen.findByText("no workspace")).toBeInTheDocument();
  });

  it.each([
    [{ backend: "state" }, "files, no shell"],
    [{ backend: "service" }, "files and a shell"],
    [{}, "files, no shell"],
  ])("names the backend in the row (%o)", async (config, expected) => {
    renderSandbox([binding("sandbox", { config })]);

    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("offers the backends and the scope instead of a generated form", async () => {
    // The objection this answers: "which backend, and who shares it" is not the
    // same kind of decision as switching on a chart tool. Enablement still is,
    // so the switch above stays exactly where every capability has it.
    renderSandbox([binding("sandbox", { config: { backend: "state" } })]);

    expect(await screen.findByRole("button", { name: /^Container/ })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Who shares it by default" })).toBeVisible();
    expect(screen.getByText("Files & shell is on")).toBeVisible();
  });

  it("keeps the header switch for every other capability", async () => {
    renderSandbox();

    await userEvent.click(screen.getByRole("button", { name: /Charts/ }));

    expect(screen.getByText(/Give this agent Charts/)).toBeVisible();
  });
});

/**
 * Delegation, which is the second capability with a panel of its own.
 *
 * The workbench's job here is only the routing and the row: what the panel then
 * shows is `subagents-section`'s own test file. What matters at this level is
 * that a capability whose configuration is partly *not* in its config blob still
 * reaches an editor, and that the list says who the agent hands work to rather
 * than how many tools delegation contributes.
 */
describe("delegation, the other capability with a panel of its own", () => {
  const DELEGATION: CapabilityCatalogEntry = {
    ...CHARTS,
    id: "subagents",
    name: "Delegation",
    category: "orchestration",
    description: "Hand part of a task to another agent.",
    tools: [{ id: "task", name: "task", description: "Delegate a task." }],
    contracts: [],
    config_schema: null,
  };

  it("says who the agent hands work to, not how many tools delegation has", async () => {
    renderWorkbench({
      catalog: [DELEGATION, CHARTS],
      selected: [
        binding("subagents", { config: { inline: [{ ...newSpecialist(), name: "summariser" }] } }),
      ],
      subagents: [{ agent_id: "a1", agent_version_id: "v1" }],
    });

    expect(await screen.findByText("2 subagents")).toBeInTheDocument();
  });

  it("says so when it hands work to nobody", async () => {
    renderWorkbench({ catalog: [DELEGATION, CHARTS] });

    expect(await screen.findByText("nobody to delegate to")).toBeInTheDocument();
  });

  it("opens the delegation panel rather than the generated form", async () => {
    renderWorkbench({ catalog: [DELEGATION, CHARTS], selected: [binding("subagents")] });

    await userEvent.click(screen.getByRole("button", { name: /^Delegation/ }));

    expect(screen.getByText("Delegates")).toBeVisible();
    expect(screen.getByText("Inline specialists")).toBeVisible();
  });

  it("leaves the panel inert until the capability is switched on", async () => {
    renderWorkbench({ catalog: [DELEGATION, CHARTS] });

    await userEvent.click(screen.getByRole("button", { name: /^Delegation/ }));

    expect(screen.getByRole("button", { name: "Add a specialist" })).toBeDisabled();
  });
});
