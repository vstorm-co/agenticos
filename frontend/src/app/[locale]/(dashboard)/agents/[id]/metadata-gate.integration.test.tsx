import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentDetail } from "@/types/agents";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * The categories/tags editor on the agent detail page.
 *
 * It hangs off the same role-level `canEdit` every editing control on the page
 * does - the avatar precedent it copies. So the contract is "no `agents:edit`
 * role, no editor", the same one the gallery card holds, and it is proven the
 * way the frontend rule wants: a mocked API, an assertion on what renders.
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

vi.mock("@/hooks", () => ({
  useAgent: () => ({
    agent: AGENT,
    isLoading: false,
    saveDraft: mutation(),
    validate: vi.fn().mockResolvedValue({ problems: [], fields: [] }),
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
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// The heavy children the build view mounts, each reaching for its own data.
// Stubbed to nothing: this test is about the page's gate, not their internals.
vi.mock("@/components/agents/publish-state", () => ({ PublishState: () => null }));
vi.mock("@/components/agents/stale-references", () => ({ StaleReferences: () => null }));
vi.mock("@/components/agents/model-profile-picker", () => ({ ModelProfilePicker: () => null }));
vi.mock("@/components/agents/model-settings-form", () => ({ ModelSettingsForm: () => null }));
vi.mock("@/components/agents/thinking-setting", () => ({ ThinkingSetting: () => null }));
vi.mock("@/components/agents/run-summary", () => ({ RunSummary: () => null }));

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

describe("the detail page's metadata editor gate", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the editor to a caller who may edit the agent", async () => {
    allowed = new Set([Perm.agentsEdit]);
    await mount();

    expect(await screen.findByRole("textbox", { name: "Add a category" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Add a tag" })).toBeInTheDocument();
  });

  it("hides the editor from a caller who may not edit", async () => {
    allowed = new Set();
    await mount();

    // The instructions card renders for everyone; the editor does not.
    await screen.findByText("Instructions");
    expect(screen.queryByRole("textbox", { name: "Add a category" })).toBeNull();
  });
});
