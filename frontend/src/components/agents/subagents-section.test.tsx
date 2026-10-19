import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SubagentsSection } from "./subagents-section";
import { DEFAULT_SUBAGENTS_CONFIG, newSpecialist } from "@/lib/agent-spec";
import type {
  Agent,
  CapabilityBindingSpec,
  CapabilityCatalogEntry,
  ExternalAgentRef,
  JsonSchema,
  SubagentRef,
} from "@/types/agents";
import type { ExternalAgent } from "@/types/external-agents";
import type { Permission } from "@/types/permissions";

const state = vi.hoisted(() => ({
  agents: [] as Agent[],
  permissions: [] as string[],
  remote: [] as ExternalAgent[],
}));

vi.mock("@/hooks", () => ({
  useAgents: () => ({
    agents: state.agents,
    total: state.agents.length,
    isLoading: false,
    promote: { mutate: vi.fn(), isPending: false },
  }),
  useExternalAgents: () => ({ agents: state.remote, isLoading: false, error: null }),
  usePermissions: () => ({
    can: (permission: Permission) => state.permissions.includes(permission),
    isLoading: false,
  }),
  useAgentVersions: () => ({
    versions: [
      { id: "v2", version: 2, note: null, published_by_user_id: null },
      { id: "v1", version: 1, note: null, published_by_user_id: null },
    ],
    isLoading: false,
  }),
  useAllAgentVersions: () => ({
    versions: [
      { id: "v2", version: 2, note: null, published_by_user_id: null },
      { id: "v1", version: 1, note: null, published_by_user_id: null },
    ],
    isLoading: false,
  }),
  // Read by the specialist editor nested below, and covered by its own file.
  useModelProviders: () => ({ catalog: [], profiles: [], isLoading: false }),
  useKnowledgeBases: () => ({ kbs: [], isLoading: false }),
  useSkills: () => ({ skills: [], total: 0, isLoading: false }),
  useSecrets: () => ({ secrets: [], isLoading: false, listError: null }),
  useProviderModels: () => ({ models: [], source: null, isLoading: false }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
}));

/**
 * The capability's schema as the contract states it.
 *
 * `inline` and `share_with_delegates` are in it, and are what this panel draws
 * itself: an array of nested specs and a choice from a set only this agent's own
 * bindings know are the two things the generated form cannot render.
 */
const CONFIG_SCHEMA: JsonSchema = {
  type: "object",
  properties: {
    inline: { type: "array", title: "Inline specialists" },
    mode: { enum: ["sync", "async", "auto"], default: "sync", title: "Delegation mode" },
    allow_dynamic: { type: "boolean", default: false, title: "Let the agent create specialists" },
    max_depth: { type: "integer", default: 1, minimum: 1, maximum: 3, title: "Delegation depth" },
    max_fanout: {
      type: "integer",
      default: 3,
      minimum: 1,
      maximum: 10,
      title: "Delegations at once",
    },
    max_result_chars: {
      type: "integer",
      default: 2000,
      minimum: 200,
      maximum: 20000,
      title: "Answer length shown per delegate",
    },
    share_with_delegates: { type: "array", title: "Share with delegates" },
  },
};

const DELEGATION: CapabilityCatalogEntry = {
  recommended: null,
  id: "subagents",
  name: "Delegation",
  category: "orchestration",
  description: "Hand part of a task to another agent.",
  side_effecting: false,
  scopes: ["agents:delegate"],
  tools: [{ id: "task", name: "task", description: "Delegate a task." }],
  contracts: [],
  config_schema: CONFIG_SCHEMA,
  requires_secret: null,
};

const CHARTS: CapabilityCatalogEntry = {
  ...DELEGATION,
  id: "charts",
  name: "Charts",
  category: "analysis",
  description: "Draw a chart.",
  scopes: [],
  tools: [],
  config_schema: null,
};

function binding(overrides: Partial<CapabilityBindingSpec> = {}): CapabilityBindingSpec {
  return {
    id: "subagents",
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: true,
    ...overrides,
  };
}

function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "a1",
    slug: "researcher",
    name: "Researcher",
    description: null,
    status: "published",
    visibility: "private",
    owner_user_id: null,
    current_version_id: "v2",
    can_run: false,
    ...overrides,
  };
}

// `null` rather than `undefined` for the two absent-able props: a default
// parameter fires on `undefined`, so passing it would silently mount the present
// case and assert nothing.
function mount({
  definition = DELEGATION as CapabilityCatalogEntry | null,
  bound = binding() as CapabilityBindingSpec | null,
  catalog = [DELEGATION, CHARTS],
  parentCapabilities = [binding()],
  subagents = [] as SubagentRef[],
  externalAgents = [] as ExternalAgentRef[],
  disabled = false,
  onChange = vi.fn(),
  onSubagentsChange = vi.fn(),
  onExternalAgentsChange = vi.fn(),
}: {
  definition?: CapabilityCatalogEntry | null;
  bound?: CapabilityBindingSpec | null;
  catalog?: CapabilityCatalogEntry[];
  parentCapabilities?: CapabilityBindingSpec[];
  subagents?: SubagentRef[];
  externalAgents?: ExternalAgentRef[];
  disabled?: boolean;
  onChange?: (binding: CapabilityBindingSpec) => void;
  onSubagentsChange?: (subagents: SubagentRef[]) => void;
  onExternalAgentsChange?: (externalAgents: ExternalAgentRef[]) => void;
} = {}) {
  const view = render(
    <SubagentsSection
      definition={definition ?? undefined}
      binding={bound ?? undefined}
      catalog={catalog}
      parentCapabilities={parentCapabilities}
      parentModelProfileId={null}
      subagents={subagents}
      onChange={onChange}
      onSubagentsChange={onSubagentsChange}
      externalAgents={externalAgents}
      onExternalAgentsChange={onExternalAgentsChange}
      disabled={disabled}
    />,
  );
  return { ...view, onChange, onSubagentsChange, onExternalAgentsChange };
}

beforeEach(() => {
  state.agents = [agent()];
  state.permissions = ["agents:run", "agents:edit"];
  state.remote = [];
});

function remote(overrides: Partial<ExternalAgent> = {}): ExternalAgent {
  return {
    id: "r1",
    slug: "contract-reviewer",
    name: "Contract Reviewer",
    description: "Reads contracts.",
    card_url: "https://agents.example.com",
    endpoint_url: "https://agents.example.com/a2a",
    secret_id: null,
    skills: [],
    can_manage: true,
    created_at: "2026-10-17T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

/** Other vendors' agents, reached over A2A, beside the organization's own (#2092). */
describe("remote delegates", () => {
  it("sends somebody to register one when none is", () => {
    mount();

    expect(screen.getByRole("link", { name: "Register one" })).toHaveAttribute(
      "href",
      "/remote-agents",
    );
    expect(screen.getByRole("button", { name: "Add a remote agent" })).toBeDisabled();
  });

  it("adds a registered agent by its registration", async () => {
    state.remote = [remote()];
    const { onExternalAgentsChange } = mount();

    expect(screen.getByText("No remote agents yet.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Add a remote agent" }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Contract Reviewer/ }));

    expect(onExternalAgentsChange).toHaveBeenCalledWith([{ external_agent_id: "r1" }]);
  });

  it("sets how one is called, and removes one", async () => {
    state.remote = [remote()];
    const { onExternalAgentsChange } = mount({ externalAgents: [{ external_agent_id: "r1" }] });

    await userEvent.click(screen.getByRole("combobox", { name: "When it hands back" }));
    await userEvent.click(await screen.findByRole("option", { name: "Wait for it" }));
    expect(onExternalAgentsChange).toHaveBeenLastCalledWith([
      { external_agent_id: "r1", preferred_mode: "sync" },
    ]);

    expect(screen.getByRole("button", { name: "Add a remote agent" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Remove Contract Reviewer" }));
    expect(onExternalAgentsChange).toHaveBeenLastCalledWith([]);
  });

  it("names a registration that is gone, and a handle another delegate claims", () => {
    state.remote = [remote({ slug: "researcher" })];
    mount({
      subagents: [{ agent_id: "a1", agent_version_id: "v2" }],
      externalAgents: [{ external_agent_id: "r1" }, { external_agent_id: "gone" }],
    });

    expect(screen.getByText("A remote agent no longer registered")).toBeVisible();
    expect(screen.getAllByText(/researcher/).length).toBeGreaterThan(1);
  });

  it("counts a remote agent as configured delegation when it is switched off", () => {
    mount({ bound: binding({ enabled: false }), externalAgents: [{ external_agent_id: "r1" }] });

    expect(
      screen.getByText(/Delegation is switched off, so none of this is reached/),
    ).toBeVisible();
  });
});

describe("SubagentsSection", () => {
  it("renders nothing when the deployment did not register the capability", () => {
    // An empty section reads as something that failed to load.
    const { container } = mount({ definition: null });

    expect(container).toBeEmptyDOMElement();
  });

  it("presents delegates, specialists and policy as three separate things", () => {
    mount();

    expect(screen.getByText("Delegates")).toBeVisible();
    expect(screen.getByText("Inline specialists")).toBeVisible();
    expect(screen.getByText("Policy")).toBeVisible();
  });

  it("warns that a configured delegation which is switched off reaches nobody", () => {
    // The spec still carries the delegates and publish still validates them.
    // Silence here is how "why is it not delegating" becomes unanswerable.
    mount({
      bound: binding({ enabled: false }),
      subagents: [{ agent_id: "a1", agent_version_id: "v2" }],
    });

    expect(
      screen.getByText(/Delegation is switched off, so none of this is reached/),
    ).toBeVisible();
  });

  it("says nothing about being switched off when nothing is configured", () => {
    mount({ bound: binding({ enabled: false }) });

    expect(screen.queryByText(/Delegation is switched off/)).toBeNull();
  });

  it("does not render the generated form as well as the sections it duplicates", () => {
    // The three sections above *are* the configuration; drawing the schema in
    // full would put the policy fields on screen twice.
    mount();

    expect(screen.getAllByLabelText("Delegation depth")).toHaveLength(1);
  });
});

/**
 * A name belongs to one subagent, and the two kinds share one namespace.
 *
 * Computed here rather than in either list because it is the one rule that spans
 * both, and because the delegate's half of it is its agent's slug - which only
 * this component, holding the agent listing, can resolve.
 */
describe("the namespace delegates and specialists share", () => {
  it("names a specialist that answers to a delegate's handle", () => {
    mount({
      bound: binding({ config: { inline: [{ ...newSpecialist(), name: "researcher" }] } }),
      subagents: [{ agent_id: "a1", agent_version_id: "v2" }],
    });

    expect(screen.getAllByText(/also called researcher/)).toHaveLength(2);
  });

  it("has no handle to compare for a delegate it cannot resolve", () => {
    // An agent the caller cannot see contributes no name to the namespace, so
    // nothing here claims a clash it cannot know about. The row says the
    // delegate is unreachable, which is the problem that actually needs fixing.
    mount({
      bound: binding({ config: { inline: [{ ...newSpecialist(), name: "researcher" }] } }),
      subagents: [{ agent_id: "gone-1", agent_version_id: "v2" }],
    });

    expect(screen.queryByText(/also called/)).toBeNull();
    expect(screen.getByText("An agent you cannot see")).toBeVisible();
  });

  it("says nothing when the two names differ", () => {
    mount({
      bound: binding({ config: { inline: [{ ...newSpecialist(), name: "writer" }] } }),
      subagents: [{ agent_id: "a1", agent_version_id: "v2" }],
    });

    expect(screen.queryByText(/also called/)).toBeNull();
  });
});

describe("the policy", () => {
  it("leaves every field a schema can render to the generated form", () => {
    // A field added to the capability appears here without anybody editing this
    // file, which is the whole reason the backend publishes a schema.
    mount();

    expect(screen.getByLabelText("Delegation depth")).toBeVisible();
    expect(screen.getByLabelText("Delegations at once")).toBeVisible();
    expect(screen.getByLabelText("Answer length shown per delegate")).toBeVisible();
    expect(screen.getByLabelText("Let the agent create specialists")).toBeVisible();
    expect(screen.getByLabelText("Delegation mode")).toBeVisible();
  });

  it("does not offer a text box for the two fields it draws itself", () => {
    // `inline` is a list of nested specs and `share_with_delegates` a choice
    // from this agent's own bindings; a generated string field for either is a
    // control whose every answer the server refuses.
    mount();

    expect(screen.queryByLabelText("Inline specialists")).toBeNull();
    expect(screen.queryByLabelText("Share with delegates")).toBeNull();
  });

  it("writes a policy field into the binding's config", async () => {
    // Typed onto a stored value: a field with a default is never empty, and this
    // component is controlled by a spy, so what is on screen does not move
    // between keystrokes.
    const { onChange } = mount({ bound: binding({ config: { max_fanout: 1 } }) });

    await userEvent.type(screen.getByLabelText("Delegations at once"), "5");

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ max_fanout: 15 }) }),
    );
  });

  it("renders no fields for a schema that declares none", () => {
    // Which is what is left of the contract's schema once `inline` and
    // `share_with_delegates` come out of it, if a deployment ever published only
    // those two.
    mount({ definition: { ...DELEGATION, config_schema: { type: "object" } } });

    expect(screen.getByText("Policy")).toBeVisible();
    expect(screen.queryByLabelText("Delegation depth")).toBeNull();
  });

  it("says so rather than showing an empty policy when no schema is published", () => {
    // Which is this deployment today: the capability is not registered, so the
    // section would otherwise be a heading with nothing underneath it.
    mount({ definition: { ...DELEGATION, config_schema: null } });

    expect(screen.getByText(/publishes no configuration schema/)).toBeVisible();
  });
});

describe("what delegates inherit", () => {
  it("offers only what the parent is itself bound to", () => {
    // Sharing a capability nobody granted the parent would make a delegate the
    // quiet route to one the organization refused.
    mount({ parentCapabilities: [binding(), binding({ id: "charts" })] });

    expect(screen.getByRole("switch", { name: "Share Charts with delegates" })).toBeVisible();
  });

  it("never offers delegation itself", () => {
    // A delegate that inherited it would delegate on, and depth is what
    // `max_depth` bounds.
    mount({ parentCapabilities: [binding()] });

    expect(screen.queryByRole("switch", { name: /Share Delegation/ })).toBeNull();
    expect(screen.getByText(/bound to nothing else, so there is nothing to pass on/)).toBeVisible();
  });

  it("does not offer a capability the parent switched off", () => {
    mount({ parentCapabilities: [binding(), binding({ id: "charts", enabled: false })] });

    expect(screen.queryByRole("switch", { name: /Share Charts/ })).toBeNull();
  });

  it("records what was shared, and un-records it", async () => {
    const { onChange } = mount({ parentCapabilities: [binding(), binding({ id: "charts" })] });

    await userEvent.click(screen.getByRole("switch", { name: "Share Charts with delegates" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: { share_with_delegates: ["charts"] } }),
    );
  });

  it("drops a capability that was shared and is no longer", async () => {
    const { onChange } = mount({
      bound: binding({ config: { share_with_delegates: ["charts"] } }),
      parentCapabilities: [binding(), binding({ id: "charts" })],
    });

    await userEvent.click(screen.getByRole("switch", { name: "Share Charts with delegates" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: { share_with_delegates: [] } }),
    );
  });
});

describe("editing a binding that does not exist yet", () => {
  it("writes nothing, rather than patching undefined where somebody clicked", async () => {
    // The row's switch is what creates the binding; until it does there is
    // nothing to patch.
    const { onChange } = mount({ bound: null, parentCapabilities: [] });

    await userEvent.click(screen.getByRole("button", { name: "Add a specialist" }));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("still reads the shipped defaults, so nothing claims a policy nobody set", () => {
    mount({ bound: null, parentCapabilities: [] });

    expect(DEFAULT_SUBAGENTS_CONFIG.mode).toBe("sync");
    expect(screen.getByText("Inline specialists")).toBeVisible();
  });
});
