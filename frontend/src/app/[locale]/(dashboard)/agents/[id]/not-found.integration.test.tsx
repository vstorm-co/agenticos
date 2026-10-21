import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import { ApiError } from "@/lib/api-error";
import type { AgentDetail } from "@/types/agents";
import type { Permission } from "@/types/permissions";

/**
 * The agent detail page when the read fails.
 *
 * A link to an agent of another organization - or one since deleted - answers
 * 404, which leaves `agent` undefined with `isLoading` already false: the
 * skeleton guard cannot tell that from a slow first load. An agent deleted from
 * another tab answers 404 on a refetch while the cache still holds it. Either
 * way the page says the agent is unavailable, with a way back to the list; any
 * other failure of a refetch leaves the Builder where it was.
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

const read = vi.hoisted(() => ({ agent: undefined as unknown, error: null as unknown }));

const mutation = () => ({
  mutate: vi.fn(),
  mutateAsync: vi.fn().mockResolvedValue({}),
  isPending: false,
  variables: undefined,
  data: undefined,
});

vi.mock("@/hooks", async () => {
  const { useUrlState } =
    await vi.importActual<typeof import("@/hooks/use-url-state")>("@/hooks/use-url-state");
  return {
    useUrlState,
    useAgent: () => ({
      agent: read.agent,
      isLoading: false,
      error: read.error,
      fetchedAt: 0,
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
    useAgentVersion: () => ({ version: undefined, isLoading: false }),
    useAgentVersions: () => ({ versions: [], total: 0, isLoading: false }),
    useAllAgentVersions: () => ({ versions: [] }),
    useProviderModels: () => ({ models: [], source: null, isLoading: false }),
    useSecretPurposes: () => ({ purposes: [] }),
    useSecrets: () => ({ secrets: [] }),
    useCapabilityCatalog: () => ({ capabilities: [] }),
    usePromptVariables: () => ({ variables: [] }),
    useDelegationTree: () => ({ tree: null, isLoading: false, error: null }),
    useEmbeds: () => ({ embeds: [] }),
    useExposures: () => ({ exposures: [] }),
    useKnowledgeBases: () => ({ kbs: [], isLoading: false, listError: null }),
    useMcpCatalog: () => ({ servers: [], isLoading: false, error: null }),
    usePlatformMcpTools: () => ({ tools: [], isLoading: false, error: null }),
    useModelProviders: () => ({
      profiles: [],
      profilesStatus: "loaded",
      refetchProfiles: vi.fn(),
      isLoading: false,
      deleteProfile: mutation(),
      createProfile: mutation(),
      catalog: [],
    }),
    useMcpConnections: () => ({ connections: [] }),
    useOrgMcpConnections: () => ({
      connections: [],
      test: vi.fn(),
      isLoading: false,
      error: null,
    }),
    usePermissions: () => ({
      can: (_permission: Permission) => true,
      isLoaded: true,
    }),
    useRuns: () => ({ runs: [] }),
    useSkills: () => ({ skills: [], total: 0, isLoading: false, error: null }),
  };
});
vi.mock("@/hooks/use-context", () => ({
  useContextFiles: () => ({ files: [], total: 0, isLoading: false, error: null }),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push }),
  usePathname: () => "/agents/a1",
  // `createNavigation` wraps these at module scope, so the page's import graph
  // fails to load without them even though nothing here redirects.
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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

const PARAMS = Promise.resolve({ id: "a1", locale: "en" });

async function mount() {
  await act(async () => {
    render(<AgentBuilderPage params={PARAMS} />, { wrapper });
    await PARAMS;
  });
}

describe("the agent detail page for an unreadable agent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    read.agent = undefined;
    read.error = new ApiError(404, "Agent not found");
  });

  it("says the agent is unavailable instead of holding the skeleton", async () => {
    await mount();

    expect(await screen.findByText("Agent not available")).toBeInTheDocument();
    // The server's reason, so a 404 reads as "not found" rather than a bare frame.
    expect(screen.getByText("Agent not found")).toBeInTheDocument();
    // Never the Builder: no skeleton and no tabs behind the refusal.
    expect(screen.queryByRole("tab", { name: "Build" })).toBeNull();
  });

  it("offers a way back to the Agents list", async () => {
    await mount();

    fireEvent.click(await screen.findByRole("button", { name: "Back to agents" }));
    expect(push).toHaveBeenCalledWith("/agents");
  });

  it("says so too when the agent is deleted while its page is open", async () => {
    read.agent = AGENT;
    await mount();

    expect(await screen.findByText("Agent not available")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Build" })).toBeNull();
  });

  it("keeps the Builder open when a refetch fails for another reason", async () => {
    read.agent = AGENT;
    read.error = new ApiError(500, "Server error");
    await mount();

    expect(await screen.findByRole("tab", { name: "Build" })).toBeInTheDocument();
    expect(screen.queryByText("Agent not available")).toBeNull();
  });
});
