import { beforeAll, describe, expect, it, vi } from "vitest";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CapabilityWorkbench } from "./capability-workbench";
import type { AgentResources } from "./capability-resources";
import { jsonSchemaType } from "./capability-settings";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

import type { ContextFileSummary } from "@/types/providers";

const { imageProviders } = vi.hoisted(() => ({ imageProviders: vi.fn() }));
vi.mock("@/hooks/use-model-providers", () => ({
  useImageProviders: () => imageProviders(),
}));

// The memory panel's one action, which needs a query client this file does not
// provide; `clear-agent-memory` covers the dialog and the call it makes.
vi.mock("@/hooks/use-memory", () => ({
  useClearAgentMemory: () => ({ mutateAsync: vi.fn(), isPending: false }),
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
  useExternalAgents: () => ({ agents: [], isLoading: false, error: null }),
  useAgentVersions: () => ({ versions: [], isLoading: false }),
  useAllAgentVersions: () => ({ versions: [], isLoading: false }),
  useModelProviders: () => ({ catalog: [], profiles: [], isLoading: false }),
  useKnowledgeBases: () => ({ kbs: [], isLoading: false }),
  useSkills: () => ({ skills: [], total: 0, isLoading: false }),
  useProviderModels: () => ({ models: [], source: null, isLoading: false }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
}));

const CHARTS: CapabilityCatalogEntry = {
  recommended: null,
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

const MEMORY_FILES: CapabilityCatalogEntry = {
  ...CHARTS,
  id: "memory_files",
  name: "Memory files",
  category: "knowledge",
  description: "Notes the agent keeps of its own across conversations.",
  tools: [{ id: "read_memory", name: "read_memory", description: "Read one note by name." }],
  contracts: [],
};

const MEMORY_MEM0: CapabilityCatalogEntry = {
  ...MEMORY_FILES,
  id: "memory_mem0",
  name: "Memory (mem0)",
  description: "Semantic memory kept in a mem0 service rather than here.",
  tools: [{ id: "recall", name: "recall", description: "Recall facts by meaning." }],
};

const CONTEXT: CapabilityCatalogEntry = {
  ...CHARTS,
  id: "context",
  name: "Context",
  category: "knowledge",
  description: "Standing knowledge this organization has written down.",
  tools: [
    { id: "list_context", name: "list_context", description: "Get an overview of all files." },
    { id: "read_context", name: "read_context", description: "Read one context file." },
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

/** Open a capability's settings panel from its card. */
async function openCapability(name: string) {
  await userEvent.click(screen.getByRole("button", { name: `${name} settings` }));
}

function renderWorkbench(props: Partial<Parameters<typeof CapabilityWorkbench>[0]> = {}) {
  return render(
    <CapabilityWorkbench
      agentId="agent-1"
      catalog={[CHARTS, CONTEXT]}
      selected={[]}
      onToggle={vi.fn()}
      onChange={vi.fn()}
      subagents={[]}
      onSubagentsChange={vi.fn()}
      externalAgents={[]}
      onExternalAgentsChange={vi.fn()}
      resources={NO_RESOURCES}
      modelProfileId={null}
      {...props}
    />,
  );
}

describe("the capability workbench", () => {
  it("offers to clear an agent's notes from inside the capability that keeps them", async () => {
    // The only thing anybody does to memory from the console: there is no
    // browsing surface, because what an agent wrote about a named colleague is
    // not a screen an operator pages through (#1470). A store nobody can clear
    // is a liability, though, so the action has to live somewhere.
    renderWorkbench({
      catalog: [MEMORY_FILES],
      selected: [binding("memory_files")],
    });

    await openCapability("Memory files");

    expect(screen.getByText("Clear this agent's memory")).toBeInTheDocument();
  });

  it("says the clear does not reach mem0 when the agent also keeps memories there", async () => {
    // mem0 addresses memories per person, so nothing can empty one agent's
    // namespace wholesale - and somebody believing it did would stop looking.
    renderWorkbench({
      catalog: [MEMORY_FILES, MEMORY_MEM0],
      selected: [binding("memory_files"), binding("memory_mem0")],
    });

    await openCapability("Memory files");

    expect(screen.getByText(/does not reach/)).toBeInTheDocument();
  });

  it("offers no clear for a capability that keeps nothing", async () => {
    renderWorkbench({ selected: [binding("charts")] });

    await openCapability("Charts");

    expect(screen.queryByText("Clear this agent's memory")).not.toBeInTheDocument();
  });

  it("offers no clear until memory is actually granted", async () => {
    // Reading a capability is not granting it, and an inert panel must not carry
    // a live destructive button.
    renderWorkbench({ catalog: [MEMORY_FILES], selected: [] });

    await openCapability("Memory files");

    expect(screen.queryByText("Clear this agent's memory")).not.toBeInTheDocument();
  });

  it("explains a capability it has words for: uses, needs and what it never does", async () => {
    renderWorkbench();

    await openCapability("Charts");

    expect(screen.getByText("For example")).toBeInTheDocument();
    expect(screen.getByText("Sales this month by region, as bars")).toBeInTheDocument();
    expect(screen.getByText("Never changes the data it draws.")).toBeInTheDocument();
  });

  it("explains nothing more for a capability the console has no words for", async () => {
    renderWorkbench({ catalog: [{ ...CHARTS, id: "from_a_plugin", name: "Plugin" }] });
    await openCapability("Plugin");

    expect((await screen.findAllByText(CHARTS.description)).length).toBeGreaterThan(0);
    expect(screen.queryByText("For example")).not.toBeInTheDocument();
  });

  it("names a category in plain words, and keeps an unknown one as it came", async () => {
    renderWorkbench({ catalog: [CHARTS, { ...CONTEXT, category: "from_a_plugin" }] });

    expect(await screen.findByText("Work with data")).toBeInTheDocument();
    expect(screen.getByText("from_a_plugin")).toBeInTheDocument();
  });

  it("shows what a capability offers without switching it on", async () => {
    // Otherwise the only way to learn what granting it does is to grant it.
    renderWorkbench();

    await openCapability("Context");
    await openTools();

    expect(screen.getByText("list_context")).toBeInTheDocument();
    expect(screen.getByText("read_context")).toBeInTheDocument();
  });

  it("shows an ungranted capability at full detail, not an abridgement", async () => {
    // The whole point of dropping the second, smaller rendering: the way to find
    // out what granting a capability involves used to be to grant it. Approval,
    // the editable description and the argument list are what that rendering
    // left out, so they are what this asserts.
    renderWorkbench();

    await openCapability("Charts");

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

    await openCapability("Charts");
    await openTools();

    expect(screen.getByLabelText("Description the model reads")).toBeDisabled();
  });

  it("grants the capability on show from the panel, not only from the list", async () => {
    // The list scrolls on its own, so the capability being read can be off
    // screen from the row that grants it.
    const onToggle = vi.fn();
    renderWorkbench({ onToggle });

    await openCapability("Charts");
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
    await openCapability("Charts");

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

    await openCapability("Charts");
    await userEvent.click(screen.getByRole("switch", { name: "Charts enabled" }));

    expect(onToggle).toHaveBeenCalledWith("charts");
  });

  it("reading a capability is not granting it", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ onToggle });

    await openCapability("Context");

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
    renderWorkbench({ selected: [binding("charts"), binding("context")] });
    await openCapability("Charts");

    const panel = screen.getByRole("group", { name: "Charts" });
    expect(within(panel).getByText("charts")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Context" })).not.toBeInTheDocument();
  });

  it("offers the whole description the model reads, not its first line", async () => {
    // The description editor holds the full contract text: an override
    // replaces everything the model is told, so editing a summary-only field
    // would silently drop the rest.
    renderWorkbench({ selected: [binding("charts")] });
    await openCapability("Charts");
    await openTools();

    expect(screen.getByLabelText("Description the model reads")).toHaveValue(
      "Draw a chart of numbers you already have.\n\nFor a scatter chart, give every row a numeric x and y.",
    );
  });

  it("names the arguments the model has to fill in", async () => {
    renderWorkbench({ selected: [binding("charts")] });
    await openCapability("Charts");
    await openTools();

    await userEvent.click(screen.getByText("Arguments (3)"));

    expect(screen.getByText("chart_type")).toBeInTheDocument();
    // Two of the three are required, and which is which decides whether an
    // agent's rewording of the tool can leave one out.
    expect(screen.getAllByText("required")).toHaveLength(2);
  });
});

describe("jsonSchemaType", () => {
  it("searches the tools too, because that is what somebody is looking for", async () => {
    // Nobody knows which capability owns `create_chart`.
    const filler = Array.from({ length: 8 }, (_, index) => ({
      ...CONTEXT,
      id: `filler-${index}`,
      name: `Filler ${index}`,
      category: "other",
      tools: [],
    }));
    renderWorkbench({ catalog: [CHARTS, ...filler] });

    await userEvent.type(screen.getByLabelText("Search capabilities…"), "create_chart");

    expect(screen.getByRole("button", { name: "Charts settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Filler 0 settings" })).toBeNull();
  });

  it("says nothing matched rather than showing an empty column", async () => {
    const filler = Array.from({ length: 8 }, (_, index) => ({
      ...CONTEXT,
      id: `filler-${index}`,
      name: `Filler ${index}`,
    }));
    renderWorkbench({ catalog: [CHARTS, ...filler] });

    await userEvent.type(screen.getByLabelText("Search capabilities…"), "zzz");

    expect(screen.getByText(/No capability or tool matches/)).toBeInTheDocument();
  });

  describe("advanced capabilities", () => {
    const COMPACTION: CapabilityCatalogEntry = {
      ...CHARTS,
      id: "compaction",
      name: "Long conversations",
      category: "utility",
      tools: [],
      contracts: [],
    };

    it("shelves them last, after everything an agent needs to start", () => {
      // Each answers a problem met only once an agent works; a page opening on
      // them reads as homework before starting (#2070).
      renderWorkbench({ catalog: [COMPACTION, CHARTS] });

      const shelves = screen
        .getAllByRole("region")
        .map((shelf) => shelf.getAttribute("aria-label"));
      expect(shelves).toEqual(["Work with data", "Advanced"]);
    });
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

describe("the workspace, which is a card like the rest and a detail unlike it", () => {
  const SANDBOX: CapabilityCatalogEntry = {
    ...CHARTS,
    id: "sandbox",
    name: "Sandbox",
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

  it("offers the backends and the scope instead of a generated form", async () => {
    // The objection this answers: "which backend, and who shares it" is not the
    // same kind of decision as switching on a chart tool. Enablement still is,
    // and it is the switch on the panel's own title row.
    renderSandbox([binding("sandbox", { config: { backend: "state" } })]);
    await openCapability("Sandbox");

    expect(await screen.findByRole("button", { name: /^Container/ })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Who shares it by default" })).toBeVisible();
    expect(screen.getByRole("switch", { name: "Sandbox enabled" })).toBeVisible();
  });

  it("grants the workspace from its own panel too", async () => {
    // The switch is on the panel's title row for every capability, the bespoke
    // panels included - it was a card above them, and a card is what went.
    const onToggle = vi.fn();
    renderWorkbench({ catalog: [SANDBOX, CHARTS], onToggle });
    await openCapability("Sandbox");

    await userEvent.click(screen.getByRole("switch", { name: "Sandbox enabled" }));

    expect(onToggle).toHaveBeenCalledWith("sandbox");
  });

  it("keeps the panel's own switch for every other capability", async () => {
    // The switch used to be a card above the panel, headed "Charts is on" with a
    // sentence under it - two lines of chrome per capability for one control that
    // is also on the card you opened it from. The card went; the switch moved
    // onto the panel's title row.
    renderSandbox();

    await openCapability("Charts");

    expect(screen.getByRole("switch", { name: "Charts enabled" })).toBeVisible();
  });
});

/**
 * Delegation, which is the second capability with a panel of its own.
 *
 * The workbench's job here is only the routing: what the panel then shows is
 * `subagents-section`'s own test file. What matters at this level is that a
 * capability whose configuration is partly *not* in its config blob still
 * reaches an editor.
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

  it("opens the delegation panel rather than the generated form", async () => {
    renderWorkbench({ catalog: [DELEGATION, CHARTS], selected: [binding("subagents")] });

    await openCapability("Delegation");

    expect(screen.getByText("Delegates")).toBeVisible();
    expect(screen.getByText("Inline specialists")).toBeVisible();
  });

  it("leaves the panel inert until the capability is switched on", async () => {
    renderWorkbench({ catalog: [DELEGATION, CHARTS] });

    await openCapability("Delegation");

    expect(screen.getByRole("button", { name: "Add a specialist" })).toBeDisabled();
  });

  it("grants delegation from its own panel too", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ catalog: [DELEGATION, CHARTS], onToggle });

    await openCapability("Delegation");
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

    await openCapability("Context");

    expect(screen.getByRole("tab", { name: "Context files" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("glossary")).toBeVisible();
  });

  it("opens on Settings for a capability that reads nothing of the organization's", async () => {
    // Which is most of them: no resources tab at all, rather than an empty one.
    renderWorkbench({ catalog: [CONTEXT, CHARTS], selected: [binding("charts")] });

    await openCapability("Charts");

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

    await openCapability("Image generation");

    expect(screen.getByLabelText("Provider")).toBeVisible();
    expect(screen.getByLabelText("Model")).toBeVisible();
  });

  it("grants it from the panel's own switch", async () => {
    const onToggle = vi.fn();
    renderWorkbench({ catalog: [IMAGE, CHARTS], onToggle });

    await openCapability("Image generation");
    await userEvent.click(screen.getByRole("switch", { name: "Image generation enabled" }));

    expect(onToggle).toHaveBeenCalledWith("image_generation");
  });
});

describe("the workbench as illustrated cards", () => {
  it("shelves the catalog by category and opens settings in a panel", async () => {
    const PORTALS = { ...CHARTS, id: "portals", name: "Portals", category: "teleportation" };
    renderWorkbench({ catalog: [CHARTS, CONTEXT, PORTALS], selected: [binding("charts")] });

    expect(screen.getByRole("region", { name: "Work with data" })).toBeInTheDocument();
    // A category the console has no words for yet keeps the registry's own.
    expect(screen.getByRole("region", { name: "teleportation" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Knowledge and memory" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Context settings" }));
    const panel = screen.getByRole("dialog");
    expect(within(panel).getByRole("heading", { name: "Context settings" })).toBeInTheDocument();
    expect(within(panel).getByRole("switch", { name: "Context enabled" })).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says when a search matches nothing", async () => {
    renderWorkbench();

    await userEvent.type(screen.getByPlaceholderText("Search capabilities…"), "teleport");

    expect(screen.getByText(/teleport/)).toBeInTheDocument();
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("marks a recommended capability on its card", () => {
    renderWorkbench({
      catalog: [
        {
          ...CHARTS,
          recommended: {
            id: "charts",
            config: {},
            approval: "default",
            tool_approval: {},
            tool_overrides: {},
            secret_id: null,
            enabled: true,
          },
        },
        CONTEXT,
      ],
    });

    expect(screen.getAllByText("Recommended")).toHaveLength(1);
  });
});
