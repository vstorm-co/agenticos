import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentDetail, AgentKind, AgentSpec } from "@/types/agents";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import { useOnboardingStore } from "@/stores/onboarding-store";

/**
 * What a system agent's page holds, and what it leaves out.
 *
 * Only the platform runs a system agent, so its page keeps what changes how it
 * works - instructions, model, budget, its context files and skills, whether it
 * searches the knowledge bases of its runs - and drops
 * whatever belongs to a chat, a tool or a release a person manages: starters,
 * voice, step limits, reviewers, approvals, environments to pin, a baseline to
 * set. Each case renders an ordinary agent beside it, so an absence is the page's
 * decision rather than a label nobody rendered.
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

const saveDraft = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

const page = vi.hoisted(() => ({
  kind: "judge" as AgentKind,
  systemKey: "eval_judge" as string | null,
  access: { can_edit: true, can_publish: true },
  draft: undefined as unknown,
  permissions: [] as Permission[],
  params: "",
  versions: [] as { version: number }[],
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
    useCapabilityCatalog: () => ({ capabilities: [] }),
    usePromptVariables: () => ({ variables: [] }),
    useDelegationTree: () => ({ tree: null, isLoading: false, error: null }),
    useExposures: () => ({ exposures: [] }),
    useEmbeds: () => ({ embeds: [] }),
    useKnowledgeBases: () => ({ kbs: [] }),
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
    useSkills: () => ({ skills: [], total: 0 }),
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
vi.mock("@/hooks/use-context", () => ({ useContextFiles: () => ({ files: [], total: 0 }) }));

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
    // Where a system agent picks what an ordinary one picks in its Toolbox.
    expect(screen.queryByText("Context files and skills") !== null).toBe(!offered);
  });

  it("picks its context files and skills where the Voice card would be", async () => {
    await mount();

    const header = screen
      .getByText("Context files and skills")
      .closest('[data-tour="agent-system-resources"]');
    const card = within(header?.parentElement as HTMLElement);
    expect(card.getByRole("heading", { name: "Context files" })).toBeInTheDocument();
    expect(card.getByRole("heading", { name: "Skills" })).toBeInTheDocument();
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

describe("a system agent's knowledge base search", () => {
  const search = () => screen.getByRole("switch", { name: "Use the knowledge base" });
  const steps = () => screen.queryByRole("spinbutton", { name: "Max steps" });

  async function settle() {
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
  }

  it("is offered on Build beside its context files, and never to an ordinary agent", async () => {
    await mount();
    expect(document.querySelector('[data-tour="agent-system-knowledge"]')?.textContent).toContain(
      "Knowledge base",
    );
    expect(search()).not.toBeChecked();
    expect(steps()).toBeNull();
  });

  it("is not on an ordinary agent's page", async () => {
    viewing("agent");
    await mount();

    expect(screen.queryByRole("switch", { name: "Use the knowledge base" })).toBeNull();
  });

  it("binds the search with its steps, and drops the binding when switched off", async () => {
    await mount();
    vi.useFakeTimers();

    fireEvent.click(search());
    fireEvent.change(steps() as HTMLElement, { target: { value: "4" } });
    await settle();
    expect(saveDraft).toHaveBeenLastCalledWith({
      ...CLEAN_DRAFT,
      capabilities: [binding("thinking"), binding("knowledge")],
      max_steps: 4,
    });

    fireEvent.click(search());
    expect(steps()).toBeNull();
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
    vi.useFakeTimers();
    await settle();

    expect(search()).toBeChecked();
    expect(steps()).toHaveValue(2);
    expect(saveDraft).not.toHaveBeenCalled();
  });

  it("cannot be switched by somebody who may only read the agent", async () => {
    page.access = { can_edit: false, can_publish: false };
    page.permissions = [Perm.agentsEdit];
    await mount();

    expect(search()).toBeDisabled();
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
