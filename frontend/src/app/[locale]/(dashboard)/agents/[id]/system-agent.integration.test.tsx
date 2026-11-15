import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentDetail, AgentKind, AgentSpec, CapabilityCatalogEntry } from "@/types/agents";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import { useOnboardingStore } from "@/stores/onboarding-store";

/** Regression coverage retained for the ordinary Agent Builder after removing helper pages. */

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

/** A draft stored before a regular agent's save refused tools, starters and voice. */
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

const saveDraft = vi.hoisted(() => vi.fn(async (spec: AgentSpec) => ({ draft_spec: spec })));

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
  MarkdownEditor: ({ toolbar }: { toolbar?: ReactNode }) => <>{toolbar}</>,
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

describe("the header of a regular agent's page", () => {
  it("is not worn by an ordinary agent", async () => {
    viewing("agent");
    await mount();

    expect(screen.queryByText(/System agent/)).toBeNull();
  });
});

describe("a regular agent's tabs", () => {
  const tabs = () => screen.getAllByRole("tab").map((tab) => tab.textContent);

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
      "Failure learning",
    ]);
  });
});

describe("a regular agent's Toolbox", () => {
  const offered = () =>
    screen
      .getAllByRole("switch", { name: /^Give this agent / })
      .map((control) => control.getAttribute("aria-label")?.replace("Give this agent ", ""));

  async function openPanel(name: string) {
    await userEvent.click(screen.getByRole("button", { name: `${name} settings` }));
    return screen.getByRole("group", { name });
  }

  beforeEach(() => {
    page.params = "tab=toolbox";
  });

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

  it("offers an ordinary agent's Knowledge panel its collections", async () => {
    viewing("agent");
    await mount();
    const panel = await openPanel("Knowledge search");

    expect(within(panel).getByRole("tab", { name: "Collections" })).toBeInTheDocument();
    expect(within(panel).getByText("Handbook")).toBeInTheDocument();
    expect(within(panel).queryByRole("spinbutton", { name: "Max steps" })).toBeNull();
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
});

describe("a regular agent's Limits tab", () => {
  const OUT = ["Max steps per run", "Stop tool-call loops", "Code mode"];
  const KEPT = ["Monthly (USD)", "Budget alerts", "Usage reports", "Tracing"];

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

describe("a regular agent's History tab", () => {
  it("leaves an ordinary agent's environments to be managed", async () => {
    viewing("agent");
    page.params = "tab=history";
    await mount();

    expect(screen.getByText(/A publish mints a version/)).toBeInTheDocument();
    expect(screen.getByTestId("environments")).toHaveAttribute("data-system", "false");
    expect(screen.getByTestId("versions")).toHaveAttribute("data-promotes", "true");
  });
});

describe("saving a regular agent's draft", () => {
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

describe("the walkthrough on a regular agent's page", () => {
  it("knows an ordinary agent's page is not", async () => {
    viewing("agent");
    await mount();

    expect(useOnboardingStore.getState().systemAgentPage).toBe(false);
  });
});
