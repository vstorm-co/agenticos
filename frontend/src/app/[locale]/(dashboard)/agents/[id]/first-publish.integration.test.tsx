import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentSpec } from "@/types/agents";
import type { ProfilesStatus } from "@/hooks/use-model-providers";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * What the Builder says the moment an agent is first published (#2131): that it
 * is live, and where else people could reach it - the Availability tab, which
 * people who needed a widget or a hosted page did not find on their own.
 *
 * The harness is the model panel spec's; only the publish flow is exercised.
 *
 * (The model panel spec's own note follows, kept with the harness it explains.)
 *
 * The Builder's Model panel, and who is allowed to see the half of it that writes.
 *
 * Choosing which model an agent runs on is `agents:edit`. Creating one is not:
 * the form posts `/providers/model-profiles`, and the bin beside a saved model
 * deletes something every agent in the organization may be pointed at - both
 * `connections:manage`. This page passed neither flag conditionally, so a member
 * who may build an agent and not manage its connections was offered the form and
 * told by a 403.
 *
 * Mounting the page rather than the picker on purpose: `ModelProfilePicker` has
 * always taken the two flags and `model-profile-picker.test.tsx` covers what it
 * does with them. What was wrong was the value this caller passed, which is not
 * visible from anywhere else.
 */

const MODEL_PROFILE = {
  id: "p-1",
  label: "openai default",
  provider: "openai",
  model: "gpt-5",
  secret_id: "s-1",
};

const refetchProfiles = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

const state = {
  permissions: [] as Permission[],
  profiles: [MODEL_PROFILE] as (typeof MODEL_PROFILE)[],
  // Both queries settle successfully by default; a case that wants the failed
  // or still-pending read says so, because that is where an empty list stops
  // meaning "the organization has none".
  profilesStatus: "loaded" as ProfilesStatus,
  permissionsLoaded: true,
  versions: [] as { version: number }[],
  nextPublished: 1,
};

vi.mock("@/hooks", async () => {
  // The real one: the Builder keeps its tab in `?tab=`, as local state here.
  const { useUrlState } =
    await vi.importActual<typeof import("@/hooks/use-url-state")>("@/hooks/use-url-state");
  return {
    useUrlState,
    useAgent: () => ({
      agent: {
        id: "a-1",
        name: "Support",
        status: "draft",
        has_avatar: false,
        draft_spec: {
          name: "Support",
          instructions: "Be helpful.",
          model_profile_id: null,
          model_settings: {},
          capabilities: [],
          collection_ids: [],
          skill_ids: [],
          context_ids: [],
          mcp_servers: [],
          subagents: [],
        } satisfies AgentSpec,
      },
      isLoading: false,
      saveDraft: { mutateAsync: vi.fn(), isPending: false },
      validate: async () => ({ problems: [], fields: [] }),
      publish: {
        mutateAsync: vi.fn().mockResolvedValue({ version: state.nextPublished }),
        isPending: false,
      },
      rollback: { mutateAsync: vi.fn() },
      setAvatar: { mutateAsync: vi.fn(), isPending: false },
      setColor: { mutate: vi.fn(), isPending: false },
      setMetadata: { mutate: vi.fn(), isPending: false },
      setA2a: { mutate: vi.fn(), isPending: false },
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
    useAgentVersions: () => ({ versions: state.versions }),
    useAllAgentVersions: () => ({ versions: [] }),
    useCapabilityCatalog: () => ({ capabilities: [] }),
    usePromptVariables: () => ({ variables: [] }),
    useDelegationTree: () => ({ tree: null, isLoading: false, error: null }),
    useExposures: () => ({ exposures: [] }),
    useEmbeds: () => ({ embeds: [] }),
    useKnowledgeBases: () => ({ kbs: [] }),
    useMcpCatalog: () => ({ servers: [] }),
    useModelProviders: () => ({
      profiles: state.profiles,
      profilesStatus: state.profilesStatus,
      refetchProfiles,
      isLoading: false,
      deleteProfile: { mutate: vi.fn() },
      createProfile: { mutateAsync: vi.fn(), isPending: false },
      catalog: [],
    }),
    useMcpConnections: () => ({ connections: [] }),
    useOrgMcpConnections: () => ({ connections: [] }),
    usePermissions: () => ({
      can: (permission: Permission) => state.permissions.includes(permission),
      isLoaded: state.permissionsLoaded,
    }),
    useProviderModels: () => ({ models: [], source: null, isLoading: false }),
    useRuns: () => ({ runs: [] }),
    useSecretPurposes: () => ({ purposes: [] }),
    useSecrets: () => ({ secrets: [] }),
    useSkills: () => ({ skills: [], total: 0 }),
  };
});

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

/**
 * The page reads its route params with `use()`, so the first render suspends and
 * the tree only exists after that promise settles - awaited here rather than in
 * every assertion.
 */
async function mount() {
  await act(async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Suspense fallback={null}>
          <AgentBuilderPage params={Promise.resolve({ id: "a-1" })} />
        </Suspense>
      </QueryClientProvider>,
    );
  });
}

beforeEach(() => {
  state.permissions = [Perm.agentsEdit, Perm.agentsPublish];
  state.versions = [];
  state.profiles = [MODEL_PROFILE];
  state.profilesStatus = "loaded";
  state.permissionsLoaded = true;
});

describe("the first publish", () => {
  async function publish() {
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish" }));
  }

  it("points at where else people can reach the agent, and opens it", async () => {
    await mount();
    await publish();

    expect(await screen.findByText(/choose where else people reach it/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open Availability" }));

    expect(screen.getByRole("tab", { name: "Availability" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByText(/choose where else people reach it/)).not.toBeInTheDocument();
  });

  it("says nothing of the kind on a later version", async () => {
    state.versions = [{ version: 1 }];
    await mount();
    await publish();

    expect(screen.queryByText(/choose where else people reach it/)).not.toBeInTheDocument();
  });
});
