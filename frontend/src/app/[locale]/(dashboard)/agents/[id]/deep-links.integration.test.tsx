import type { AgentDraftUpdate } from "@/types/agents";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentDetail } from "@/types/agents";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * What the agent detail page does with where it was sent from.
 *
 * The Evals tab: every read behind it takes `runs:view`, so without it the tab
 * is not offered at all rather than opening onto a refusal. And `?publish=1`
 * from an eval run: it walks the same path the Publish button does - store,
 * validate, then ask - and only for someone who may publish.
 */

const AGENT: AgentDetail = {
  id: "a1",
  slug: "support",
  name: "Support",
  description: null,
  status: "draft",
  visibility: "private",
  owner_user_id: "u1",
  current_version_id: null,
  can_run: false,
  has_avatar: false,
  categories: [],
  tags: [],
  draft_revision: "base",
  draft_spec: {
    name: "Support",
    description: null,
    instructions: "",
    model_profile_id: null,
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    context_ids: [],
    mcp_servers: [],
    budget: null,
  },
};

let allowed: Set<Permission>;
const page = vi.hoisted(() => ({
  kind: "agent" as AgentDetail["kind"],
  params: "",
  validate: (() => undefined) as unknown,
  agent: undefined as unknown,
  attention: [] as {
    agent_id: string;
    rated_down: number;
    failed_runs: number;
    failing_suites?: number;
  }[],
  sessions: [] as { id: string; status: string; created_at: string }[],
  gaps: 0,
  gapsEnabled: [] as (boolean | undefined)[],
}));
vi.mock("@/hooks/use-usage-stats", () => ({
  useAgentAttention: () => ({ agents: page.attention }),
}));
vi.mock("@/hooks/use-improvements", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-improvements")>()),
  useImprovements: () => ({ sessions: page.sessions }),
}));
vi.mock("@/hooks/use-knowledge-gaps", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-knowledge-gaps")>()),
  useKnowledgeGaps: (_scope: unknown, query?: { enabled?: boolean }) => {
    page.gapsEnabled.push(query?.enabled);
    return { total: page.gaps };
  },
}));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/agents/a1",
  useSearchParams: () => new URLSearchParams(page.params),
}));

vi.mock("@/hooks", async () => {
  // The real one: the Builder keeps its tab in `?tab=`, as local state here.
  const { useUrlState } =
    await vi.importActual<typeof import("@/hooks/use-url-state")>("@/hooks/use-url-state");
  return {
    useUrlState,
    useAgent: () => ({
      agent: { ...(page.agent as AgentDetail), kind: page.kind },
      isLoading: false,
      saveDraft: {
        mutateAsync: vi.fn(async ({ spec }: AgentDraftUpdate) => ({
          draft_spec: spec,
          draft_revision: "saved",
        })),
        isPending: false,
      },
      validate: page.validate,
      publish: {
        mutateAsync: vi.fn().mockResolvedValue({ version: 1 }),
        isPending: false,
      },
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
    useAgentVersions: () => ({ versions: [] }),
    useAllAgentVersions: () => ({ versions: [] }),
    useDraftBase: () => ({ base: undefined }),
    useCapabilityCatalog: () => ({ capabilities: [] }),
    usePromptVariables: () => ({ variables: [] }),
    useDelegationTree: () => ({ tree: null, isLoading: false, error: null }),
    useExposures: () => ({ exposures: [] }),
    useEmbeds: () => ({ embeds: [] }),
    useKnowledgeBases: () => ({ kbs: [] }),
    useMcpCatalog: () => ({ servers: [] }),
    usePlatformMcpTools: () => ({ tools: [], isLoading: false, error: null }),
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
      can: (permission: Permission) => allowed.has(permission),
      isLoaded: true,
    }),
    useProviderModels: () => ({ models: [], source: null, isLoading: false }),
    useRuns: () => ({ runs: [] }),
    useSecretPurposes: () => ({ purposes: [] }),
    useSecrets: () => ({ secrets: [] }),
    useSkills: () => ({ skills: [], total: 0 }),
  };
});

vi.mock("@/components/mcp/mcp-server-list", () => ({
  McpServerList: ({ canManageOrganization }: { canManageOrganization: boolean }) => (
    <div data-testid="embedded-mcp-management">{String(canManageOrganization)}</div>
  ),
}));

// The page's eval parts read their own queries; this test is not about them.
vi.mock("@/hooks/use-eval-runs", () => ({
  useDraftEvalRuns: () => ({ runs: [] }),
  useEvalArmSpec: () => ({ spec: undefined }),
  useRunsADataset: () => false,
}));
vi.mock("@/components/evals/draft-eval-note", () => ({ DraftEvalNote: () => null }));
vi.mock("@/components/evals/evals-panel", () => ({
  EvalsPanel: ({ actions }: { actions?: ReactNode }) => (
    <div data-testid="eval-results">{actions}</div>
  ),
}));
vi.mock("@/components/evals/suites/eval-suites-card", () => ({
  EvalSuitesCard: () => <div data-testid="eval-suites" />,
}));
vi.mock("@/components/authoring/assistant-strip", () => ({
  AssistantStrip: () => <div data-testid="suggestions">Suggestions</div>,
}));
vi.mock("@/components/evals/start-eval-dialog", () => ({ StartEvalDialog: () => null }));
vi.mock("@/components/knowledge-gaps/knowledge-gaps-panel", () => ({
  KnowledgeGapsPanel: () => null,
}));
vi.mock("@/hooks/use-context", () => ({
  useContextFiles: () => ({ files: [], total: 0 }),
}));

vi.mock("@/stores", () => ({
  useAgentSelectionStore: (select: (state: { select: () => void }) => unknown) =>
    select({ select: vi.fn() }),
  useConversationStore: (select: (state: { reset: () => void }) => unknown) =>
    select({ reset: vi.fn() }),
  useAuthStore: (select: (state: { user: null }) => unknown) => select({ user: null }),
}));

// Composition the Model panel does not depend on. Each is covered where it
// lives; mounted here they only make the page slower and this spec's failures
// harder to read.
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => null }));
vi.mock("@/components/agents/model-settings-form", () => ({ ModelSettingsForm: () => null }));
vi.mock("@/components/agents/voice-card", () => ({ VoiceCard: () => null }));
vi.mock("@/components/agents/thinking-setting", () => ({ ThinkingSetting: () => null }));
vi.mock("@/components/ui/markdown-editor", () => ({
  MarkdownEditor: ({ toolbar }: { toolbar?: ReactNode }) => <>{toolbar}</>,
  MarkdownModeToggle: () => null,
}));
// What the Availability tab holds is covered where each panel lives; here the
// only question is whether the hint opens the tab.
vi.mock("@/components/agents/exposures-panel", () => ({ ExposuresPanel: () => null }));
vi.mock("@/components/agents/embeds-panel", () => ({ EmbedsPanel: () => null }));
vi.mock("@/components/triggers/triggers-panel", () => ({ TriggersPanel: () => null }));

async function mount() {
  await mountAndReturn();
}

async function mountAndReturn() {
  let mounted!: ReturnType<typeof render>;
  await act(async () => {
    mounted = render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <Suspense fallback={null}>
          <AgentBuilderPage params={Promise.resolve({ id: "a1" })} />
        </Suspense>
      </QueryClientProvider>,
    );
  });
  return mounted;
}

beforeEach(() => {
  vi.clearAllMocks();
  page.params = "";
  page.kind = "agent";
  page.validate = vi.fn().mockResolvedValue({ problems: [], fields: [], fixes: [] });
  page.agent = { ...AGENT, can_edit: true, can_publish: true };
  page.attention = [];
  page.sessions = [];
  page.gaps = 0;
  page.gapsEnabled = [];
});

describe("the detail page's Evals tab gate", () => {
  it("offers the tab to a caller who may read runs", async () => {
    allowed = new Set([Perm.runsView]);
    await mount();

    expect(await screen.findByRole("tab", { name: "Evals" })).toBeInTheDocument();
  });

  it("hides the tab from a caller who may not", async () => {
    allowed = new Set();
    await mount();

    await screen.findByRole("tab", { name: "History" });
    expect(screen.queryByRole("tab", { name: "Evals" })).toBeNull();
  });

  it("keeps a requested Evals tab open and explains the permission it needs", async () => {
    allowed = new Set();
    page.params = "tab=evals";
    await mount();

    expect(await screen.findByRole("tab", { name: "Evals" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByText(
        "Reading eval results needs runs:view. Ask an organization owner for access.",
      ),
    ).toBeVisible();
    expect(screen.queryByTestId("eval-results")).toBeNull();
  });
});

describe("the detail page's tabs", () => {
  it("run from building the agent to what it learned, with its history last", async () => {
    allowed = new Set([Perm.runsView]);
    await mount();

    await screen.findByRole("tab", { name: "History" });
    expect(screen.getAllByRole("tab").map((tab) => tab.getAttribute("data-tour"))).toEqual([
      "agent-tab-build",
      "agent-tab-toolbox",
      "agent-tab-mcp",
      "agent-tab-limits",
      "agent-tab-availability",
      "agent-tab-evals",
      "agent-tab-gaps",
      "agent-tab-history",
    ]);
  });

  it("put the Evals tab's results above its suites", async () => {
    allowed = new Set([Perm.runsView]);
    page.params = "tab=evals";
    await mount();

    const results = await screen.findByTestId("eval-results");
    expect(results.compareDocumentPosition(screen.getByTestId("eval-suites"))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
});

describe("a link naming a tab on a system agent", () => {
  it("opens no tab of a page the console does not offer, and no empty panel", async () => {
    allowed = new Set([Perm.runsView]);
    page.kind = "judge";
    for (const params of ["tab=evals", "tab=gaps"]) {
      page.params = params;
      const { unmount } = await mountAndReturn();
      expect(await screen.findByText("Resource unavailable")).toBeVisible();
      expect(screen.queryByRole("tab")).toBeNull();
      expect(screen.queryByRole("tabpanel")).toBeNull();
      expect(screen.queryByTestId("eval-results")).toBeNull();
      unmount();
    }
  });
});

describe("the detail page's Knowledge gaps tab", () => {
  it("opens when a link names it for a caller who may read runs", async () => {
    allowed = new Set([Perm.runsView]);
    page.params = "tab=gaps";
    await mount();

    expect(await screen.findByRole("tab", { name: "Knowledge gaps" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

describe("the detail page's way into Improve", () => {
  it("keeps Build focused on instructions and puts Improve and suggestions in Evals", async () => {
    allowed = new Set([Perm.runsView]);
    await mount();
    await screen.findByRole("tab", { name: "Build" });
    expect(screen.queryByRole("button", { name: "Improve" })).toBeNull();
    expect(screen.queryByTestId("suggestions")).toBeNull();
    expect(screen.getByRole("button", { name: "Publish" })).toHaveClass("bg-action");
  });

  it("offers one Improve entry in Evals", async () => {
    allowed = new Set([Perm.runsView]);
    page.params = "tab=evals";
    await mount();
    expect(await screen.findByRole("button", { name: "Improve" })).not.toHaveClass("bg-action");
    expect(screen.getAllByRole("button", { name: "Improve" })).toHaveLength(1);
    expect(screen.getByTestId("suggestions")).toBeVisible();
  });

  it("says why when people rated answers down, without taking the lead from Publish", async () => {
    allowed = new Set([Perm.runsView]);
    page.params = "tab=evals";
    page.attention = [{ agent_id: "a1", rated_down: 7, failed_runs: 1 }];
    await mount();
    const improve = await screen.findByRole("button", {
      name: "Needs attention: 7 answers rated down, 1 failed run. Improve this agent",
    });
    expect(improve).not.toHaveClass("bg-action");
    expect(screen.getByRole("button", { name: "Publish" })).toHaveClass("bg-action");
  });

  it("is linked from the agent's knowledge gaps", async () => {
    allowed = new Set([Perm.runsView]);
    page.params = "tab=gaps";
    await mount();
    const link = await screen.findByRole("link", { name: "Improve this agent from these gaps" });
    expect(link).toHaveAttribute("href", "/agents/a1?improve=resume");
    expect(link.querySelector("svg.lucide-trending-up")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("legacy helper deep links", () => {
  it.each(["tab=gaps", "tab=toolbox", "tab=datasets"])(
    "keeps helpers out of the builder for %s",
    async (query) => {
      allowed = new Set([Perm.runsView, Perm.agentsEdit]);
      page.kind = "judge";
      page.params = query;
      await mount();
      expect(await screen.findByRole("link", { name: "Back to agents" })).toHaveAttribute(
        "href",
        "/agents",
      );
      expect(screen.queryByRole("tab", { name: "Build" })).toBeNull();
    },
  );
});

describe("a publish asked for by a link", () => {
  it("validates and asks before anything goes live", async () => {
    allowed = new Set([Perm.agentsEdit, Perm.agentsPublish]);
    page.params = "tab=build&publish=1";
    await mount();

    expect(await screen.findByRole("dialog", { name: "Publish v1?" })).toBeInTheDocument();
    expect(page.validate).toHaveBeenCalledTimes(1);
  });

  it("is not offered to who may not publish this agent, whatever the role says", async () => {
    allowed = new Set([Perm.agentsEdit, Perm.agentsPublish]);
    page.agent = { ...AGENT, can_edit: true, can_publish: false };
    page.params = "tab=build&publish=1";
    await mount();

    await screen.findByText("Instructions");
    expect(page.validate).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is offered to who may publish this agent through a grant alone", async () => {
    allowed = new Set();
    page.params = "tab=build&publish=1";
    await mount();

    expect(await screen.findByRole("dialog", { name: "Publish v1?" })).toBeInTheDocument();
  });
});

describe("embedded organization MCP management", () => {
  it.each([true, false])(
    "uses mcp:manage rather than model-connection permission: %s",
    async (manageMcp) => {
      allowed = new Set([manageMcp ? Perm.mcpManage : Perm.connectionsManage]);
      page.params = "tab=mcp";
      await mount();
      if (manageMcp) {
        fireEvent.click(await screen.findByRole("button", { name: "Connect a server" }));
        expect(await screen.findByTestId("embedded-mcp-management")).toHaveTextContent("true");
      } else {
        expect(screen.queryByRole("button", { name: "Connect a server" })).toBeNull();
      }
    },
  );
});

describe("the dots on the tabs that hold what needs attention", () => {
  it("marks Evals with why, keeping the tab's own name", async () => {
    allowed = new Set([Perm.runsView]);
    page.attention = [{ agent_id: "a1", rated_down: 2, failed_runs: 0, failing_suites: 1 }];
    await mount();

    const evals = await screen.findByRole("tab", { name: "Evals" });
    expect(screen.getByRole("tab", { name: "Build" })).toHaveAttribute("aria-selected", "true");
    expect(evals).toHaveAttribute("aria-selected", "false");
    expect(evals).toHaveAccessibleDescription(
      "Needs attention: 2 answers rated down, 1 failing suite",
    );
    expect(screen.getByTestId("evals-attention")).toBeInTheDocument();
    expect(screen.queryByTestId("gaps-attention")).toBeNull();
  });

  it("marks Evals for an Improve session waiting for a person, not for one still working", async () => {
    allowed = new Set([Perm.runsView]);
    page.sessions = [{ id: "s1", status: "waiting", created_at: "2026-11-01T00:00:00Z" }];
    const { unmount } = await mountAndReturn();
    expect(await screen.findByRole("tab", { name: "Evals" })).toHaveAccessibleDescription(
      "Needs attention: an improvement waits for you",
    );
    unmount();

    page.sessions = [{ id: "s1", status: "running", created_at: "2026-11-01T00:00:00Z" }];
    await mount();
    expect(await screen.findByRole("tab", { name: "Evals" })).not.toHaveAttribute(
      "aria-describedby",
    );
    expect(screen.queryByTestId("evals-attention")).toBeNull();
  });

  it("leaves a waiting Improve session out for a reader who may not continue it", async () => {
    allowed = new Set([Perm.runsView]);
    page.agent = { ...AGENT, can_edit: false, can_publish: false };
    page.sessions = [{ id: "s1", status: "waiting", created_at: "2026-11-01T00:00:00Z" }];
    const { unmount } = await mountAndReturn();
    expect(await screen.findByRole("tab", { name: "Evals" })).not.toHaveAttribute(
      "aria-describedby",
    );
    expect(screen.queryByTestId("evals-attention")).toBeNull();
    unmount();

    page.attention = [{ agent_id: "a1", rated_down: 1, failed_runs: 0 }];
    await mount();
    expect(await screen.findByRole("tab", { name: "Evals" })).toHaveAccessibleDescription(
      "Needs attention: 1 answer rated down",
    );
  });

  it("marks Knowledge gaps with how many are open", async () => {
    allowed = new Set([Perm.runsView]);
    page.gaps = 3;
    await mount();

    expect(await screen.findByRole("tab", { name: "Knowledge gaps" })).toHaveAccessibleDescription(
      "3 open knowledge gaps",
    );
    expect(screen.getByTestId("gaps-attention")).toBeInTheDocument();
    expect(screen.queryByTestId("evals-attention")).toBeNull();
  });

  it("marks nothing when nothing waits", async () => {
    allowed = new Set([Perm.runsView]);
    await mount();

    await screen.findByRole("tab", { name: "Evals" });
    expect(screen.queryByTestId("evals-attention")).toBeNull();
    expect(screen.queryByTestId("gaps-attention")).toBeNull();
  });

  it("asks nothing and marks nothing for a reader who may not see runs, or on a system agent", async () => {
    allowed = new Set();
    page.attention = [{ agent_id: "a1", rated_down: 2, failed_runs: 0 }];
    page.gaps = 3;
    const { unmount } = await mountAndReturn();
    await screen.findByRole("tab", { name: "History" });
    expect(screen.queryByTestId("evals-attention")).toBeNull();
    expect(page.gapsEnabled.every((enabled) => enabled === false)).toBe(true);
    unmount();

    allowed = new Set([Perm.runsView]);
    page.kind = "judge";
    page.gapsEnabled = [];
    await mount();
    expect(page.gapsEnabled.length).toBeGreaterThan(0);
    expect(page.gapsEnabled.every((enabled) => enabled === false)).toBe(true);
  });
});
