import { beforeAll, describe, expect, it, vi } from "vitest";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CapabilityWorkbench } from "./capability-workbench";
import type { AgentResources } from "./capability-resources";
import { jsonSchemaType } from "./capability-settings";
import { newSpecialist } from "@/lib/agent-spec";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

import type { ContextFileSummary } from "@/types/providers";

const { imageProviders } = vi.hoisted(() => ({ imageProviders: vi.fn() }));
vi.mock("@/hooks/use-model-providers", () => ({
  useImageProviders: () => imageProviders(),
}));

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
  useAllAgentVersions: () => ({ versions: [], isLoading: false }),
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

/** An organization with nothing to give an agent - what most of these are about. */
const NO_RESOURCES: AgentResources = {
  contextFiles: [],
  contextTotal: 0,
  contextIds: [],
  onContextToggle: vi.fn(),
  collections: [],
  collectionIds: [],
  onCollectionToggle: vi.fn(),
  skills: [],
  skillTotal: 0,
  skillIds: [],
  onSkillToggle: vi.fn(),
};

/**
 * Show the focused panel's Tools tab.
 *
 * Settings and Tools are two tabs since a rich capability - a six-field form, an
 * approval and a tool whose description is a paragraph - made one scroll of two
 * unrelated jobs. Anything asserting on a tool reaches through here.
 */
async function openTools() {
  await userEvent.click(screen.getByRole("tab", { name: "Tools" }));
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
      resources={NO_RESOURCES}
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
    await openTools();

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
    await openTools();
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
    await openTools();

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

  it("takes the panel's switch away from a reader who may not edit", async () => {
    // The one control `disabled` used to leave live for them: it means both "this
    // capability is off" and "you may not edit", and an ungranted capability is
    // off - so the switch stayed clickable for a Viewer whose list row beside it
    // was already inert, and clicking it dirtied a spec they cannot save.
    const onToggle = vi.fn();
    renderWorkbench({ onToggle, disabled: true });

    const panelSwitch = screen.getByRole("switch", { name: "Charts enabled" });
    expect(panelSwitch).toBeDisabled();

    await userEvent.click(panelSwitch);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("keeps the panel's switch live for an editor, off capability and all", async () => {
    // The reason the two are separate props: a switch disabled by its own state
    // is a switch nobody can turn back on.
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

  it("offers the whole description the model reads, not its first line", async () => {
    // The description editor holds the full contract text: an override
    // replaces everything the model is told, so editing a summary-only field
    // would silently drop the rest.
    renderWorkbench({ selected: [binding("charts")] });
    await openTools();

    expect(screen.getByLabelText("Description the model reads")).toHaveValue(
      "Draw a chart of numbers you already have.\n\nFor a scatter chart, give every row a numeric x and y.",
    );
  });

  it("names the arguments the model has to fill in", async () => {
    renderWorkbench({ selected: [binding("charts")] });
    await openTools();

    await userEvent.click(screen.getByText("Arguments (3)"));

    expect(screen.getByText("chart_type")).toBeInTheDocument();
    // Two of the three are required, and which is which decides whether an
    // agent's rewording of the tool can leave one out.
    expect(screen.getAllByText("required")).toHaveLength(2);
  });
});

describe("the frame the two panes sit in", () => {
  it("lets the panel grow rather than fixing the frame's height", () => {
    // It was `lg:h-[36rem]`, to stop a shorter panel leaving the page scrolled
    // past its own content - which the browser clamps anyway: measured on this
    // page, switching away from the workspace panel at the bottom moves scrollTop
    // 2080 -> 0. What the fixed frame did leave was 400px of empty card under a
    // short panel, and a scrollbar inside the page beside the page's own.
    const { container } = renderWorkbench({ catalog: [CHARTS] });

    expect(container.querySelector(".grid")?.className).not.toContain("lg:h-[36rem]");
  });

  it("scrolls the list alone, so the page keeps one scrollbar", () => {
    // The list is a catalog of thirty and has to stay reachable beside a long
    // panel, so it is the one bounded column - sticky, capped, scrolling. The
    // panel is not: a gallery of collections is taller than any frame worth
    // fixing, and a wheel over it should move the page.
    const { container } = renderWorkbench({ catalog: [CHARTS] });

    expect(container.querySelectorAll('[class*="overflow-y-auto"]').length).toBe(1);
  });

  it("caps the list at the viewport, not at a fixed 36rem", () => {
    // Sticky and 36rem tall left a void beside a long panel - measured 532px of
    // empty gutter next to the image capability's 1108px panel. A column the
    // height of the screen is filled by the catalog instead, and on a tall screen
    // the whole list fits, so its own scrollbar stops appearing too.
    const { container } = renderWorkbench({ catalog: [CHARTS] });
    const list = container.querySelector(".grid")?.firstElementChild;

    expect(list?.className).toContain("lg:sticky");
    expect(list?.className).toContain("lg:max-h-[calc(100vh-8rem)]");
    expect(list?.className).not.toContain("lg:max-h-[36rem]");
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
    return renderWorkbench({ catalog: [SANDBOX, CHARTS], selected });
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
    // and it is the switch on the panel's own title row.
    renderSandbox([binding("sandbox", { config: { backend: "state" } })]);

    expect(await screen.findByRole("button", { name: /^Container/ })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Who shares it by default" })).toBeVisible();
    expect(screen.getByRole("switch", { name: "Files & shell enabled" })).toBeVisible();
  });

  it("grants the workspace from its own panel too", async () => {
    // The switch is on the panel's title row for every capability, the bespoke
    // panels included - it was a card above them, and a card is what went.
    const onToggle = vi.fn();
    renderWorkbench({ catalog: [SANDBOX, CHARTS], onToggle });

    await userEvent.click(screen.getByRole("switch", { name: "Files & shell enabled" }));

    expect(onToggle).toHaveBeenCalledWith("sandbox");
  });

  it("keeps the panel's own switch for every other capability", async () => {
    // The switch used to be a card above the panel, headed "Charts is on" with a
    // sentence under it - two lines of chrome per capability for one control that
    // is also in the row you clicked. The card went; the switch moved onto the
    // panel's title row, because the list scrolls and the row can be off screen.
    renderSandbox();

    await userEvent.click(screen.getByRole("button", { name: /Charts/ }));

    expect(screen.getByRole("switch", { name: "Charts enabled" })).toBeVisible();
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

  it("grants delegation from its own panel too", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ catalog: [DELEGATION, CHARTS], onToggle });

    await userEvent.click(screen.getByRole("button", { name: /^Delegation/ }));
    await userEvent.click(screen.getByRole("switch", { name: "Delegation enabled" }));

    expect(onToggle).toHaveBeenCalledWith("subagents");
  });
});

/**
 * Context, the third capability with a panel of its own.
 *
 * The routing is what matters at this level - `context-section`'s own file covers
 * what the panel then shows. The report behind it: somebody looking for "which
 * files does this agent read" opened this capability, found a read-tool switch and
 * two tool descriptions, and the files were a card two tabs away under Skills.
 */
describe("context, the capability that reads the files", () => {
  const CONTEXT: CapabilityCatalogEntry = {
    ...CHARTS,
    id: "context",
    name: "Context",
    category: "knowledge",
    description: "Put the organization's standing context into the agent.",
    tools: [{ id: "list_context", name: "list_context", description: "List the files." }],
    contracts: [],
    config_schema: null,
  };

  const FILE = {
    id: "f1",
    name: "glossary",
    description: "What the acronyms mean.",
    format: "md",
    mode: "inject",
    enabled: true,
    size_bytes: 120,
  } as ContextFileSummary;

  it("opens on what the capability was given, not on its settings", async () => {
    // The files are what somebody came to this panel to change; `expose_read_tool`
    // and a tool's prompt text are set once. Under Settings, where the picker
    // started, the first screen of the panel was a form.
    renderWorkbench({
      catalog: [CONTEXT, CHARTS],
      selected: [binding("context")],
      resources: { ...NO_RESOURCES, contextFiles: [FILE], contextTotal: 1 },
    });

    await userEvent.click(screen.getByRole("button", { name: /^Context/ }));

    expect(screen.getByRole("tab", { name: "Context files" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("glossary")).toBeVisible();
  });

  it("opens on Settings for a capability that reads nothing of the organization's", async () => {
    // Which is most of them: no resources tab at all, rather than an empty one.
    renderWorkbench({ catalog: [CONTEXT, CHARTS], selected: [binding("charts")] });

    await userEvent.click(screen.getByRole("button", { name: /^Charts/ }));

    expect(screen.getByRole("tab", { name: "Settings" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: "Context files" })).toBeNull();
  });
});

/**
 * Image generation, the fourth capability with a panel of its own.
 *
 * Whose model draws and which one are two decisions, and both lists are the
 * server's - so the routing is what matters here and `image-generation-section`'s
 * own file covers the rest.
 */
describe("image generation, whose model is a provider and a model", () => {
  // The panel asks the platform which providers can draw. Stubbed rather than
  // wrapped in a QueryClient: what this describe is about is the routing, and the
  // request belongs to `use-model-providers`' own test.
  beforeAll(() => {
    imageProviders.mockReturnValue({
      providers: [
        {
          provider: "openai",
          name: "OpenAI",
          models: [{ id: "gpt-image-2", name: "GPT Image 2", description: "The best one." }],
        },
      ],
      isLoading: false,
      isError: false,
    });
  });

  const IMAGE: CapabilityCatalogEntry = {
    ...CHARTS,
    id: "image_generation",
    name: "Image generation",
    category: "analysis",
    description: "Generate an image from a text description.",
    tools: [{ id: "generate_image", name: "generate_image", description: "Draw." }],
    contracts: [],
    config_schema: null,
  };

  it("opens its own panel rather than the generated form", async () => {
    renderWorkbench({ catalog: [IMAGE, CHARTS], selected: [binding("image_generation")] });

    await userEvent.click(screen.getByRole("button", { name: /^Image generation/ }));

    expect(screen.getByLabelText("Provider")).toBeVisible();
    expect(screen.getByLabelText("Model")).toBeVisible();
  });

  it("grants it from the panel's own switch", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ catalog: [IMAGE, CHARTS], onToggle });

    await userEvent.click(screen.getByRole("button", { name: /^Image generation/ }));
    await userEvent.click(screen.getByRole("switch", { name: "Image generation enabled" }));

    expect(onToggle).toHaveBeenCalledWith("image_generation");
  });
});
