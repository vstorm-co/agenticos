import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentDetail, AgentKind, AgentSpec, CapabilityCatalogEntry } from "@/types/agents";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import { useOnboardingStore } from "@/stores/onboarding-store";

/**
 * What a system agent's page holds, and what it leaves out.
 *
 * Only the platform runs a system agent, so its page keeps what changes how it
 * works - instructions, model, budget, and in the same Toolbox an ordinary agent
 * has, its context files, skills and whether it searches the knowledge bases of
 * its runs - and drops whatever belongs to a chat, a tool or a release a person
 * manages: starters, voice, step limits, reviewers, approvals, environments to
 * pin, a baseline to set. Each case renders an ordinary agent beside it, so an
 * absence is the page's decision rather than a label nobody rendered.
 */

function binding(id: string): AgentSpec["capabilities"][number] {
  return {
    id,
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: true,
  };
}

/** A draft stored before a system agent's save refused tools, starters and voice. */
const LEGACY_DRAFT: AgentSpec = {
  name: "Eval judge",
  description: null,
  instructions: "Grade the answer.",
  starters: ["Grade this"],
  model_profile_id: null,
  model_settings: {},
  capabilities: [binding("thinking"), binding("web_search")],
  collection_ids: ["kb1"],
  skill_ids: [],
  context_ids: [],
  mcp_servers: [
    { account: "organization", connection_id: "m1", allowed_tools: null, approval: "none" },
  ],
  subagents: [],
  budget: null,
  voice: null,
  speech_to_text: null,
};

const CLEAN_DRAFT: AgentSpec = {
  ...LEGACY_DRAFT,
  starters: [],
  capabilities: [binding("thinking")],
  collection_ids: [],
  mcp_servers: [],
};

/** A capability as the catalog lists it, with one tool so its panel has a Tools tab. */
function capability(id: string, name: string): CapabilityCatalogEntry {
  return {
    id,
    name,
    category: "knowledge",
    description: `${name} for this agent.`,
    side_effecting: false,
    scopes: [],
    tools: [{ id: `${id}_tool`, name: `${id}_tool`, description: "A tool." }],
    contracts: [],
    config_schema: null,
    requires_secret: null,
    voice: "never",
    recommended: null,
  };
}

/** What the deployment offers: a system agent may bind the last four, thinking on Build. */
const CATALOG: CapabilityCatalogEntry[] = [
  capability("web_search", "Web search"),
  capability("sandbox", "Workspace"),
  capability("thinking", "Thinking"),
  capability("knowledge", "Knowledge search"),
  capability("context", "Context"),
  capability("skills", "Skills"),
];

function file(id: string, name: string, visibility: string) {
  return {
    id,
    name,
    description: `${name}.`,
    format: "md",
    mode: "inject",
    enabled: true,
    visibility,
    size_bytes: 120,
  };
}

function skill(id: string, name: string, visibility: string) {
  return {
    id,
    name,
    description: `${name}.`,
    file_count: 1,
    category: null,
    enabled: true,
    visibility,
    built_in: false,
  };
}

const saveDraft = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

const page = vi.hoisted(() => ({
  kind: "judge" as AgentKind,
  systemKey: "eval_judge" as string | null,
  access: { can_edit: true, can_publish: true },
  draft: undefined as unknown,
  permissions: [] as Permission[],
  params: "",
  versions: [] as { version: number }[],
  catalog: [] as unknown[],
  files: [] as unknown[],
  skills: [] as unknown[],
}));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/agents/a1",
  useSearchParams: () => new URLSearchParams(page.params),
}));

vi.mock("@/hooks", async () => {
  const { useUrlState } =
    await vi.importActual<typeof import("@/hooks/use-url-state")>("@/hooks/use-url-state");
  return {
    useUrlState,
    useAgent: () => ({
      agent: {
        id: "a1",
        slug: "eval-judge",
        name: "Eval judge",
        description: null,
        status: "published",
        visibility: "org",
        owner_user_id: null,
        current_version_id: "v1",
        can_run: true,
        has_avatar: false,
        categories: [],
        tags: [],
        kind: page.kind,
        system_key: page.systemKey,
        ...page.access,
        draft_spec: page.draft,
      } as AgentDetail,
      isLoading: false,
      saveDraft: { mutateAsync: saveDraft, isPending: false },
      validate: vi.fn().mockResolvedValue({ problems: [], fields: [], fixes: [] }),
      publish: { mutateAsync: vi.fn().mockResolvedValue({ version: 1 }), isPending: false },
      rollback: { mutateAsync: vi.fn() },
      setAvatar: { mutateAsync: vi.fn(), isPending: false },
      setColor: { mutate: vi.fn(), isPending: false },
      setMetadata: { mutate: vi.fn(), isPending: false },
    }),
    useAgentEnvironments: () => ({ environments: [], promote: { mutateAsync: vi.fn() } }),
    useAgents: () => ({
      agents: [],
      clone: { mutateAsync: vi.fn() },
      archive: { mutateAsync: vi.fn() },
      unarchive: { mutateAsync: vi.fn() },
      remove: { mutateAsync: vi.fn() },
    }),
    useAgentVersion: () => ({ version: undefined, isLoading: false }),
    useAgentVersions: () => ({ versions: page.versions }),
    useAllAgentVersions: () => ({ versions: [] }),
    useDraftBase: () => ({ base: undefined }),
    useCapabilityCatalog: () => ({ capabilities: page.catalog }),
    usePromptVariables: () => ({ variables: [] }),
    useDelegationTree: () => ({ tree: null, isLoading: false, error: null }),
    useExposures: () => ({ exposures: [] }),
    useEmbeds: () => ({ embeds: [] }),
    useKnowledgeBases: () => ({ kbs: [{ id: "kb1", name: "Handbook", document_count: 1 }] }),
    useMcpCatalog: () => ({ servers: [] }),
    useMembers: () => ({ members: [] }),
    useModelProviders: () => ({
      profiles: [],
      profilesStatus: "loaded",
      refetchProfiles: vi.fn(),
      isLoading: false,
      deleteProfile: { mutate: vi.fn() },
      createProfile: { mutateAsync: vi.fn(), isPending: false },
      catalog: [],
    }),
    useMcpConnections: () => ({ connections: [] }),
    useOrgMcpConnections: () => ({ connections: [] }),
    usePermissions: () => ({
      can: (permission: Permission) => page.permissions.includes(permission),
      isLoaded: true,
    }),
    useProviderModels: () => ({ models: [], source: null, isLoading: false }),
    useRuns: () => ({ runs: [] }),
    useSecretPurposes: () => ({ purposes: [] }),
    useSecrets: () => ({ secrets: [] }),
    useSkills: () => ({ skills: page.skills, total: page.skills.length }),
  };
});

vi.mock("@/hooks/use-eval-runs", () => ({
  useDraftEvalRuns: () => ({ runs: [] }),
  useEvalArmSpec: () => ({ spec: undefined }),
  useRunsADataset: () => false,
}));
vi.mock("@/hooks/use-usage-stats", () => ({ useAgentAttention: () => ({ agents: [] }) }));
vi.mock("@/components/evals/draft-eval-note", () => ({ DraftEvalNote: () => null }));
vi.mock("@/components/authoring/assistant-strip", () => ({ AssistantStrip: () => null }));
vi.mock("@/components/evals/start-eval-dialog", () => ({ StartEvalDialog: () => null }));
vi.mock("@/hooks/use-context", () => ({
  useContextFiles: () => ({ files: page.files, total: page.files.length }),
}));

vi.mock("@/stores", () => ({
  useAgentSelectionStore: (select: (state: { select: () => void }) => unknown) =>
    select({ select: vi.fn() }),
  useConversationStore: (select: (state: { reset: () => void }) => unknown) =>
    select({ reset: vi.fn() }),
  useAuthStore: (select: (state: { user: null }) => unknown) => select({ user: null }),
  useOrgStore: (select: (state: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "org-1" }),
}));

vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => null }));
vi.mock("@/components/agents/model-settings-form", () => ({
  ModelSettingsForm: ({ verdict }: { verdict?: string }) => (
    <div data-testid="model-settings" data-verdict={verdict ?? "none"} />
  ),
}));
vi.mock("@/components/agents/thinking-setting", () => ({ ThinkingSetting: () => null }));
vi.mock("@/components/ui/markdown-editor", () => ({
  MarkdownEditor: () => null,
  MarkdownModeToggle: () => null,
}));
// Each is covered where it lives; here the question is whether the page mounts it,
// and with what.
vi.mock("@/components/agents/voice-card", () => ({
  VoiceCard: () => <div data-testid="voice-card" />,
}));
vi.mock("@/components/agents/environments-panel", () => ({
  EnvironmentsPanel: ({ system }: { system?: boolean }) => (
    <div data-testid="environments" data-system={String(system === true)} />
  ),
}));
vi.mock("@/components/agents/version-history", () => ({
  VersionHistory: ({ onPromote, canRestore }: { onPromote?: unknown; canRestore: boolean }) => (
    <div
      data-testid="versions"
      data-promotes={String(onPromote !== undefined)}
      data-restores={String(canRestore)}
    />
  ),
}));

async function mount() {
  let view: ReturnType<typeof render> | undefined;
  await act(async () => {
    view = render(
      <QueryClientProvider client={new QueryClient()}>
        <Suspense fallback={null}>
          <AgentBuilderPage params={Promise.resolve({ id: "a1" })} />
        </Suspense>
      </QueryClientProvider>,
    );
  });
  await screen.findByRole("tab", { name: "Build" });
  return view as ReturnType<typeof render>;
}

/** The name field of the name and description card: the page has other fields called "Name". */
function nameField() {
  const card = screen.getByText("Name and description").closest("[data-tour='agent-identity']");
  return within(card as HTMLElement).getByRole("textbox", { name: "Name" });
}

/** The kind of agent a case renders, the platform's seeded one or an organization's own. */
function viewing(
  kind: AgentKind,
  systemKey: string | null = kind === "agent" ? null : "eval_judge",
) {
  page.kind = kind;
  page.systemKey = systemKey;
}

beforeEach(() => {
  vi.clearAllMocks();
  viewing("judge");
  page.access = { can_edit: true, can_publish: true };
  page.draft = CLEAN_DRAFT;
  page.permissions = [Perm.agentsEdit, Perm.agentsPublish, Perm.orgSettings];
  page.params = "";
  page.versions = [];
  page.catalog = CATALOG;
  page.files = [];
  page.skills = [];
});

afterEach(() => vi.useRealTimers());

describe("the header of a system agent's page", () => {
  it("names the kind of system agent and that the platform runs it", async () => {
    await mount();

    const badge = screen.getByText("System agent · Judge");
    expect(badge).toHaveAttribute(
      "title",
      "The platform runs it for the whole organization; nobody chats with it.",
    );
  });

  it("is decided by the kind, so an organization's own system agent wears it too", async () => {
    viewing("drafter", null);
    await mount();

    expect(screen.getByText("System agent · Gap drafter")).toBeInTheDocument();
  });

  it("is not worn by an ordinary agent", async () => {
    viewing("agent");
    await mount();

    expect(screen.queryByText(/System agent/)).toBeNull();
  });
});

describe("a system agent's tabs", () => {
  const tabs = () => screen.getAllByRole("tab").map((tab) => tab.textContent);

  it("are a judge's Build, Toolbox, Limits, Datasets and History, in an ordinary agent's order", async () => {
    await mount();

    expect(tabs()).toEqual(["Build", "Toolbox", "Limits", "Datasets", "History"]);
  });

  it.each(["generator", "drafter", "classifier", "improver"] as const)(
    "are a %s's Build, Toolbox, Limits and History",
    async (kind) => {
      viewing(kind);
      await mount();

      expect(tabs()).toEqual(["Build", "Toolbox", "Limits", "History"]);
    },
  );

  it("leave an ordinary agent's tabs as they are", async () => {
    viewing("agent");
    page.permissions = [...page.permissions, Perm.runsView];
    await mount();

    expect(tabs()).toEqual([
      "Build",
      "Toolbox",
      "MCP servers",
      "Limits",
      "Availability",
      "Evals",
      "Knowledge gaps",
      "History",
    ]);
  });

  it("open the Toolbox a link names", async () => {
    page.params = "tab=toolbox";
    await mount();

    expect(screen.getByRole("tab", { name: "Toolbox" })).toHaveAttribute("aria-selected", "true");
  });

  it.each(["mcp", "availability", "evals", "gaps"])(
    "open Build for a link naming %s, which a system agent has not",
    async (tab) => {
      page.params = `tab=${tab}`;
      page.permissions = [...page.permissions, Perm.runsView];
      await mount();

      expect(screen.getByRole("tab", { name: "Build" })).toHaveAttribute("aria-selected", "true");
    },
  );
});

describe("a system agent's Build tab", () => {
  it.each([
    ["agent", true],
    ["judge", false],
  ] as const)("for a kind of %s, offers starters and voice: %s", async (kind, offered) => {
    viewing(kind);
    await mount();

    expect(screen.getByText("Instructions")).toBeInTheDocument();
    expect(document.querySelector('[data-tour="agent-starters"]') !== null).toBe(offered);
    expect(screen.queryByTestId("voice-card") !== null).toBe(offered);
  });

  it("holds none of what its Toolbox offers", async () => {
    await mount();

    const build = screen.getByRole("tabpanel", { name: "Build" });
    expect(within(build).queryByText("Context files")).toBeNull();
    expect(within(build).queryByText("Knowledge base")).toBeNull();
    expect(within(build).queryByRole("spinbutton", { name: "Max steps" })).toBeNull();
    expect(screen.queryByRole("switch", { name: /knowledge/i })).toBeNull();
  });
});

describe("a system agent's model settings", () => {
  it.each([
    ["judge", "judge"],
    ["classifier", "classifier"],
    ["drafter", "none"],
    ["generator", "none"],
    ["agent", "none"],
  ] as const)("for a kind of %s, warn about a varied verdict: %s", async (kind, verdict) => {
    viewing(kind);
    await mount();

    expect(screen.getByTestId("model-settings")).toHaveAttribute("data-verdict", verdict);
  });
});

describe("a system agent's Toolbox", () => {
  const offered = () =>
    screen
      .getAllByRole("switch", { name: /^Give this agent / })
      .map((control) => control.getAttribute("aria-label")?.replace("Give this agent ", ""));

  async function openPanel(name: string) {
    await userEvent.click(screen.getByRole("button", { name: `${name} settings` }));
    return screen.getByRole("group", { name });
  }

  async function settle() {
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
  }

  beforeEach(() => {
    page.params = "tab=toolbox";
  });

  it("offers a judge only knowledge, context and skills, thinking staying on Build", async () => {
    await mount();

    expect(offered().sort()).toEqual(["Context", "Knowledge search", "Skills"]);
  });

  it("offers a classifier no skills while it holds none", async () => {
    viewing("classifier");
    await mount();

    expect(offered().sort()).toEqual(["Context", "Knowledge search"]);
  });

  it("offers a classifier the skills it still holds only to take off", async () => {
    viewing("classifier");
    page.skills = [skill("s1", "rubric-writing", "org"), skill("s2", "team-style", "org")];
    page.draft = {
      ...CLEAN_DRAFT,
      capabilities: [binding("thinking"), binding("skills")],
      skill_ids: ["s1"],
    };
    await mount();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    expect(offered().sort()).toEqual(["Context", "Knowledge search", "Skills"]);
    const panel = await openPanel("Skills");
    expect(within(panel).getByText(/A classifier reads no skills/)).toBeVisible();
    expect(within(panel).queryByText("team-style")).toBeNull();

    fireEvent.click(within(panel).getByRole("checkbox", { name: "rubric-writing" }));
    await settle();
    expect(saveDraft).toHaveBeenLastCalledWith(CLEAN_DRAFT);
    expect(screen.queryByRole("switch", { name: "Give this agent Skills" })).toBeNull();
  });

  it.each([
    ["bound and picked", [binding("thinking"), binding("skills")], ["s1"]],
    ["picked with the capability off", [binding("thinking")], ["s1"]],
    ["bound with nothing picked", [binding("thinking"), binding("skills")], []],
  ])(
    "takes every skill off a classifier from the card's switch, %s",
    async (_state, capabilities, skillIds) => {
      viewing("classifier");
      page.skills = [skill("s1", "rubric-writing", "org")];
      page.draft = { ...CLEAN_DRAFT, capabilities, skill_ids: skillIds };
      await mount();
      vi.useFakeTimers({ shouldAdvanceTime: true });

      fireEvent.click(screen.getByRole("switch", { name: "Give this agent Skills" }));
      await settle();
      expect(saveDraft).toHaveBeenLastCalledWith(CLEAN_DRAFT);
      expect(offered().sort()).toEqual(["Context", "Knowledge search"]);
    },
  );

  it("offers an ordinary agent the whole catalog but thinking", async () => {
    viewing("agent");
    await mount();

    expect(offered().sort()).toEqual([
      "Context",
      "Knowledge search",
      "Skills",
      "Web search",
      "Workspace",
    ]);
  });

  it("sets a search's steps in its Knowledge panel, and picks no collection there", async () => {
    await mount();
    const panel = await openPanel("Knowledge search");

    expect(within(panel).getByRole("tab", { name: "Knowledge base" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      within(panel).getByText(/against the knowledge bases of the agent it grades/),
    ).toBeVisible();
    expect(within(panel).queryByText("Handbook")).toBeNull();
    expect(within(panel).getByRole("spinbutton", { name: "Max steps" })).toBeDisabled();
  });

  it("offers an ordinary agent's Knowledge panel its collections", async () => {
    viewing("agent");
    await mount();
    const panel = await openPanel("Knowledge search");

    expect(within(panel).getByRole("tab", { name: "Collections" })).toBeInTheDocument();
    expect(within(panel).getByText("Handbook")).toBeInTheDocument();
    expect(within(panel).queryByRole("spinbutton", { name: "Max steps" })).toBeNull();
  });

  it("binds the search with its steps from the card's switch, and drops it again", async () => {
    await mount();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    fireEvent.click(screen.getByRole("switch", { name: "Give this agent Knowledge search" }));
    const panel = await openPanel("Knowledge search");
    fireEvent.change(within(panel).getByRole("spinbutton", { name: "Max steps" }), {
      target: { value: "4" },
    });
    await settle();
    expect(saveDraft).toHaveBeenLastCalledWith({
      ...CLEAN_DRAFT,
      capabilities: [binding("thinking"), binding("knowledge")],
      max_steps: 4,
    });

    fireEvent.click(screen.getByRole("switch", { name: "Give this agent Knowledge search" }));
    await settle();
    expect(saveDraft).toHaveBeenLastCalledWith({ ...CLEAN_DRAFT, max_steps: 4 });
  });

  it("opens a stored search as it is, without approvals and without saving", async () => {
    page.draft = {
      ...CLEAN_DRAFT,
      capabilities: [binding("thinking"), { ...binding("knowledge"), approval: "required" }],
      max_steps: 2,
    };
    await mount();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const panel = await openPanel("Knowledge search");
    await settle();

    expect(screen.getByRole("switch", { name: "Give this agent Knowledge search" })).toBeChecked();
    expect(within(panel).getByRole("spinbutton", { name: "Max steps" })).toHaveValue(2);
    expect(saveDraft).not.toHaveBeenCalled();
  });

  it("offers no approval its save would refuse", async () => {
    await mount();
    const panel = await openPanel("Knowledge search");

    await userEvent.click(within(panel).getByRole("tab", { name: "Settings" }));
    expect(within(panel).queryByText("Human approval")).toBeNull();
    await userEvent.click(within(panel).getByRole("tab", { name: "Tools" }));
    expect(within(panel).getByText("knowledge_tool")).toBeInTheDocument();
    expect(within(panel).queryByText("Approval")).toBeNull();
  });

  it("offers only the files and skills the whole organization shares, and those it holds", async () => {
    page.files = [
      file("f1", "grading-policy", "org"),
      file("f2", "team-notes", "private"),
      file("f3", "old-notes", "private"),
    ];
    page.skills = [skill("s1", "rubric-writing", "org"), skill("s2", "team-style", "private")];
    page.draft = { ...CLEAN_DRAFT, context_ids: ["f3"] };
    await mount();

    const context = await openPanel("Context");
    expect(within(context).getByText("grading-policy")).toBeInTheDocument();
    expect(within(context).getByRole("checkbox", { name: "old-notes" })).toBeChecked();
    expect(within(context).queryByText("team-notes")).toBeNull();
    expect(
      within(context).getByText(/Only what is shared with the whole organization is offered/),
    ).toBeInTheDocument();

    const skills = await openPanel("Skills");
    expect(within(skills).getByText("rubric-writing")).toBeInTheDocument();
    expect(within(skills).queryByText("team-style")).toBeNull();
  });

  it("offers an ordinary agent every file it may read", async () => {
    viewing("agent");
    page.files = [file("f1", "grading-policy", "org"), file("f2", "team-notes", "private")];
    await mount();

    const context = await openPanel("Context");
    expect(within(context).getByText("team-notes")).toBeInTheDocument();
    expect(
      within(context).queryByText(/Only what is shared with the whole organization/),
    ).toBeNull();
  });

  it("changes nothing for somebody who may only read the agent", async () => {
    page.access = { can_edit: false, can_publish: false };
    page.permissions = [Perm.agentsEdit];
    page.draft = { ...CLEAN_DRAFT, capabilities: [binding("thinking"), binding("knowledge")] };
    await mount();

    for (const control of screen.getAllByRole("switch", { name: /^Give this agent / })) {
      expect(control).toBeDisabled();
    }
    const panel = await openPanel("Knowledge search");
    expect(within(panel).getByRole("switch", { name: "Knowledge search enabled" })).toBeDisabled();
    expect(within(panel).getByRole("spinbutton", { name: "Max steps" })).toBeDisabled();
  });
});

describe("a system agent's Limits tab", () => {
  const OUT = ["Max steps per run", "Stop tool-call loops", "Code mode"];
  const KEPT = ["Monthly (USD)", "Budget alerts", "Usage reports", "Tracing"];

  it("keeps the budget, its alerts and tracing, and nothing about steps or approvals", async () => {
    page.params = "tab=limits";
    await mount();

    for (const label of KEPT) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    for (const label of OUT) expect(screen.queryByText(label)).toBeNull();
    expect(screen.queryByText("Run reviewers")).toBeNull();
    expect(screen.queryByRole("switch", { name: "Approval requests" })).toBeNull();
  });

  it("leaves an ordinary agent's limits as they are", async () => {
    viewing("agent");
    page.params = "tab=limits";
    await mount();

    for (const label of [...KEPT, ...OUT]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("Run reviewers")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Approval requests" })).toBeInTheDocument();
  });
});

describe("a system agent's History tab", () => {
  it("says its default environment follows every publish, and offers restoring, not promoting", async () => {
    page.params = "tab=history";
    await mount();

    expect(
      screen.getByText(/A system agent runs on its default environment, which follows every/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("environments")).toHaveAttribute("data-system", "true");
    expect(screen.getByTestId("versions")).toHaveAttribute("data-promotes", "false");
    expect(screen.getByTestId("versions")).toHaveAttribute("data-restores", "true");
  });

  it("leaves an ordinary agent's environments to be managed", async () => {
    viewing("agent");
    page.params = "tab=history";
    await mount();

    expect(screen.getByText(/A publish mints a version/)).toBeInTheDocument();
    expect(screen.getByTestId("environments")).toHaveAttribute("data-system", "false");
    expect(screen.getByTestId("versions")).toHaveAttribute("data-promotes", "true");
  });
});

describe("a system agent's first publish", () => {
  async function publish() {
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish" }));
  }

  it.each([
    ["agent", true],
    ["judge", false],
  ] as const)("for a kind of %s, offers to set a baseline: %s", async (kind, offered) => {
    viewing(kind);
    await mount();
    await publish();

    await act(async () => {});
    expect(screen.queryByRole("button", { name: "Set a baseline" }) !== null).toBe(offered);
  });
});

describe("who may change a system agent", () => {
  const NOTICE = /Only an organization administrator can change a system agent/;

  it("tells an editor of agents without organization settings why it is read-only", async () => {
    page.access = { can_edit: false, can_publish: false };
    page.permissions = [Perm.agentsEdit, Perm.agentsPublish];
    await mount();

    expect(screen.getByText(NOTICE)).toBeInTheDocument();
    expect(nameField()).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
  });

  it.each([
    ["an administrator", "judge", [Perm.agentsEdit, Perm.orgSettings], true],
    ["a viewer, who edits no agent anywhere", "judge", [Perm.agentsView], false],
    ["an editor of an ordinary agent shared read-only", "agent", [Perm.agentsEdit], false],
  ] as const)("says nothing to %s", async (_who, kind, permissions, canEdit) => {
    viewing(kind);
    page.access = { can_edit: canEdit, can_publish: canEdit };
    page.permissions = [...permissions];
    await mount();

    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});

describe("a system agent's overflow menu", () => {
  async function menu() {
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    return screen.findByRole("menu");
  }

  it("offers no archive or delete for the platform's own", async () => {
    await mount();

    const items = await menu();
    expect(within(items).getByText("Export YAML")).toBeInTheDocument();
    expect(within(items).queryByText("Archive")).toBeNull();
    expect(within(items).queryByText("Delete permanently")).toBeNull();
  });

  it("offers both for an organization's own, whose refusal the server explains", async () => {
    viewing("judge", null);
    await mount();

    const items = await menu();
    expect(within(items).getByText("Archive")).toBeInTheDocument();
    expect(within(items).getByText("Delete permanently")).toBeInTheDocument();
  });
});

describe("saving a system agent's draft", () => {
  it("stores nothing just for opening a draft that holds what its save refuses", async () => {
    page.draft = LEGACY_DRAFT;
    await mount();
    vi.useFakeTimers();
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });

    expect(saveDraft).not.toHaveBeenCalled();
    expect(screen.queryByText("Unsaved")).toBeNull();
  });

  it("leaves what its save refuses out of the draft it sends", async () => {
    page.draft = LEGACY_DRAFT;
    await mount();

    vi.useFakeTimers();
    fireEvent.change(nameField(), {
      target: { value: "Refunds judge" },
    });
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });

    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(saveDraft).toHaveBeenCalledWith({
      ...CLEAN_DRAFT,
      name: "Refunds judge",
    });
  });

  it("sends an ordinary agent's draft as it stands", async () => {
    viewing("agent");
    page.draft = LEGACY_DRAFT;
    await mount();

    vi.useFakeTimers();
    fireEvent.change(nameField(), {
      target: { value: "Support" },
    });
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });

    expect(saveDraft).toHaveBeenCalledWith({ ...LEGACY_DRAFT, name: "Support" });
  });
});

describe("the walkthrough on a system agent's page", () => {
  it("knows the page on screen is a system agent's while it is mounted", async () => {
    const view = await mount();
    expect(useOnboardingStore.getState().systemAgentPage).toBe(true);

    view.unmount();
    expect(useOnboardingStore.getState().systemAgentPage).toBe(false);
  });

  it("knows an ordinary agent's page is not", async () => {
    viewing("agent");
    await mount();

    expect(useOnboardingStore.getState().systemAgentPage).toBe(false);
  });
});
