import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
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
      saveDraft: { mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false },
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
    useCapabilityCatalog: () => ({ capabilities: [] }),
    usePromptVariables: () => ({ variables: [] }),
    useDelegationTree: () => ({ tree: null, isLoading: false, error: null }),
    useExposures: () => ({ exposures: [] }),
    useEmbeds: () => ({ embeds: [] }),
    useKnowledgeBases: () => ({ kbs: [] }),
    useMcpCatalog: () => ({ servers: [] }),
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

// The page's eval parts read their own queries; this test is not about them.
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalArmSpec: () => ({ spec: undefined }),
  useRunsADataset: () => false,
}));
vi.mock("@/components/evals/draft-eval-note", () => ({ DraftEvalNote: () => null }));
vi.mock("@/components/evals/evals-panel", () => ({
  EvalsPanel: () => <div data-testid="eval-results" />,
}));
vi.mock("@/components/evals/suites/eval-suites-card", () => ({
  EvalSuitesCard: () => <div data-testid="eval-suites" />,
}));
vi.mock("@/components/authoring/assistant-strip", () => ({ AssistantStrip: () => null }));
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
  MarkdownEditor: () => null,
  MarkdownModeToggle: () => null,
}));
// What the Availability tab holds is covered where each panel lives; here the
// only question is whether the hint opens the tab.
vi.mock("@/components/agents/exposures-panel", () => ({ ExposuresPanel: () => null }));
vi.mock("@/components/agents/embeds-panel", () => ({ EmbedsPanel: () => null }));
vi.mock("@/components/triggers/triggers-panel", () => ({ TriggersPanel: () => null }));

async function mount() {
  await act(async () => {
    render(
      <Suspense fallback={null}>
        <AgentBuilderPage params={Promise.resolve({ id: "a1" })} />
      </Suspense>,
    );
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  page.params = "";
  page.kind = "agent";
  page.validate = vi.fn().mockResolvedValue({ problems: [], fields: [], fixes: [] });
  page.agent = { ...AGENT, can_edit: true, can_publish: true };
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

  it("opens on Build when a link names a tab the caller does not have", async () => {
    allowed = new Set();
    page.params = "tab=evals";
    await mount();

    expect(await screen.findByRole("tab", { name: "Build" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
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

describe("a system agent's page", () => {
  it("holds what changes how it works, and nothing else", async () => {
    allowed = new Set([Perm.runsView, Perm.agentsEdit]);
    page.kind = "drafter";
    page.params = "tab=gaps";
    await mount();

    expect(await screen.findByRole("tab", { name: "Build" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    for (const name of ["Toolbox", "Availability", "Evals", "Knowledge gaps"]) {
      expect(screen.queryByRole("tab", { name })).toBeNull();
    }
  });

  it.each(["judge", "generator"] as const)(
    "offers a %s neither tools, exposure nor evals",
    async (kind) => {
      allowed = new Set([Perm.runsView, Perm.agentsEdit]);
      page.kind = kind;
      await mount();

      await screen.findByRole("tab", { name: "History" });
      const tabs = screen.getAllByRole("tab").map((tab) => tab.getAttribute("data-tour"));
      expect(tabs).not.toContain("agent-tab-toolbox");
      expect(tabs).not.toContain("agent-tab-mcp");
      expect(tabs).not.toContain("agent-tab-availability");
      expect(tabs).not.toContain("agent-tab-evals");
      expect(screen.queryByRole("tab", { name: "Datasets" }) !== null).toBe(kind === "judge");
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
