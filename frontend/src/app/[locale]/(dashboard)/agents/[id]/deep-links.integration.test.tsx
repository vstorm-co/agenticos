import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
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

const mutation = () => ({
  mutate: vi.fn(),
  mutateAsync: vi.fn().mockResolvedValue({}),
  isPending: false,
  variables: undefined,
  data: undefined,
});

let allowed: Set<Permission>;
const page = vi.hoisted(() => ({
  params: "",
  validate: (() => undefined) as unknown,
}));

vi.mock("@/hooks", () => ({
  useAgent: () => ({
    agent: AGENT,
    isLoading: false,
    saveDraft: mutation(),
    validate: page.validate,
    publish: mutation(),
    rollback: mutation(),
    setAvatar: mutation(),
    setColor: mutation(),
    setMetadata: mutation(),
  }),
  useAgentEnvironments: () => ({ environments: [], promote: mutation() }),
  useAgents: () => ({
    agents: [],
    clone: mutation(),
    archive: mutation(),
    unarchive: mutation(),
    remove: mutation(),
  }),
  useAgentVersions: () => ({ versions: [], total: 0, isLoading: false }),
  useCapabilityCatalog: () => ({ capabilities: [] }),
  useDelegationTree: () => ({ tree: null, isLoading: false, error: null }),
  useEmbeds: () => ({ embeds: [] }),
  useExposures: () => ({ exposures: [] }),
  useKnowledgeBases: () => ({ kbs: [], isLoading: false, listError: null }),
  useMcpCatalog: () => ({ servers: [], isLoading: false, error: null }),
  useModelProviders: () => ({ profiles: [], profilesStatus: "loaded" }),
  useOrgMcpConnections: () => ({
    connections: [],
    test: vi.fn(),
    isLoading: false,
    error: null,
  }),
  usePermissions: () => ({
    can: (permission: Permission) => allowed.has(permission),
    isLoaded: true,
  }),
  useRuns: () => ({ runs: [] }),
  useSkills: () => ({ skills: [], total: 0, isLoading: false, error: null }),
}));
vi.mock("@/hooks/use-context", () => ({
  useContextFiles: () => ({ files: [], total: 0, isLoading: false, error: null }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/agents/a1",
  useSearchParams: () => new URLSearchParams(page.params),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// The heavy children the build view mounts, each reaching for its own data.
// Stubbed to nothing: this test is about the page's gate, not their internals.
vi.mock("@/components/agents/publish-state", () => ({ PublishState: () => null }));
vi.mock("@/components/agents/stale-references", () => ({ StaleReferences: () => null }));
vi.mock("@/components/agents/model-profile-picker", () => ({ ModelProfilePicker: () => null }));
vi.mock("@/components/agents/model-settings-form", () => ({ ModelSettingsForm: () => null }));
vi.mock("@/components/agents/thinking-setting", () => ({ ThinkingSetting: () => null }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>{children}</Suspense>
    </QueryClientProvider>
  );
}

// A stable promise: `use()` re-suspends forever if handed a fresh one per render.
const PARAMS = Promise.resolve({ id: "a1", locale: "en" });

async function mount() {
  await act(async () => {
    render(<AgentBuilderPage params={PARAMS} />, { wrapper });
    await PARAMS;
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  page.params = "";
  page.validate = vi.fn().mockResolvedValue({ problems: [], fields: [] });
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
});

describe("a publish asked for by a link", () => {
  it("validates and asks before anything goes live", async () => {
    allowed = new Set([Perm.agentsEdit, Perm.agentsPublish]);
    page.params = "tab=build&publish=1";
    await mount();

    expect(await screen.findByRole("dialog", { name: "Publish v1?" })).toBeInTheDocument();
    expect(page.validate).toHaveBeenCalledTimes(1);
  });

  it("is not offered to who may not publish", async () => {
    allowed = new Set([Perm.agentsEdit]);
    page.params = "tab=build&publish=1";
    await mount();

    await screen.findByText("Instructions");
    expect(page.validate).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
