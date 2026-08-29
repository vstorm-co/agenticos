import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentSpec } from "@/types/agents";
import type { ProfilesStatus } from "@/hooks/use-model-providers";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
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
};

vi.mock("@/hooks", () => ({
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
    validate: { mutateAsync: vi.fn() },
    publish: { mutateAsync: vi.fn(), isPending: false },
    rollback: { mutateAsync: vi.fn() },
    setAvatar: { mutateAsync: vi.fn(), isPending: false },
    setColor: { mutate: vi.fn(), isPending: false },
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
}));

vi.mock("@/hooks/use-context", () => ({
  useContextFiles: () => ({ files: [], total: 0 }),
}));

vi.mock("@/stores", () => ({
  useAgentSelectionStore: (select: (state: { select: () => void }) => unknown) =>
    select({ select: vi.fn() }),
  useConversationStore: (select: (state: { reset: () => void }) => unknown) =>
    select({ reset: vi.fn() }),
}));

// Composition the Model panel does not depend on. Each is covered where it
// lives; mounted here they only make the page slower and this spec's failures
// harder to read.
vi.mock("@/components/agents/agent-avatar", () => ({ AgentAvatar: () => null }));
vi.mock("@/components/agents/model-settings-form", () => ({ ModelSettingsForm: () => null }));
vi.mock("@/components/agents/thinking-setting", () => ({ ThinkingSetting: () => null }));
vi.mock("@/components/ui/markdown-editor", () => ({ MarkdownEditor: () => null }));

/**
 * The page reads its route params with `use()`, so the first render suspends and
 * the tree only exists after that promise settles - awaited here rather than in
 * every assertion.
 */
async function mount() {
  await act(async () => {
    render(
      <Suspense fallback={null}>
        <AgentBuilderPage params={Promise.resolve({ id: "a-1" })} />
      </Suspense>,
    );
  });
}

beforeEach(() => {
  state.permissions = [Perm.agentsEdit];
  state.profiles = [MODEL_PROFILE];
  state.profilesStatus = "loaded";
  state.permissionsLoaded = true;
});

describe("the Builder's model panel", () => {
  it("lets somebody who may manage connections create and delete a model", async () => {
    state.permissions = [Perm.agentsEdit, Perm.connectionsManage];
    await mount();

    expect(await screen.findByRole("button", { name: "Add model" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove openai default" })).toBeInTheDocument();
  });

  it("offers no add-model form to a builder without connections:manage", async () => {
    await mount();

    // The panel is still there and still chooses - what is gone is the write.
    expect(await screen.findByRole("radio", { name: "openai default" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
  });

  it("offers no way to delete a model to that builder either", async () => {
    // A separate claim from creating one: it takes a profile away from under
    // every agent in the organization that is pointed at it.
    await mount();

    expect(await screen.findByRole("radio", { name: "openai default" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove openai/ })).toBeNull();
  });

  it("says up front that the org has no model and adding one needs a permission it lacks", async () => {
    // The dead end #591 fixes: a builder with agents:edit but not
    // connections:manage, in an organization with no model, can create a draft
    // that publish alone will refuse. The panel says so where the control would
    // have been, not at publish.
    state.profiles = [];
    await mount();

    expect(await screen.findByText(/no model yet/)).toBeInTheDocument();
  });

  it("stays quiet when a builder who cannot add a model still has one to choose", async () => {
    // A model exists; there is no dead end, so the notice would only be noise.
    await mount();

    expect(await screen.findByRole("radio", { name: "openai default" })).toBeInTheDocument();
    expect(screen.queryByText(/no model yet/)).toBeNull();
  });

  it("stays quiet when the builder can add a model themselves", async () => {
    // No model, but connections:manage - the add control is theirs, so the
    // notice pointing them at an admin would be wrong.
    state.permissions = [Perm.agentsEdit, Perm.connectionsManage];
    state.profiles = [];
    await mount();

    expect(await screen.findByRole("button", { name: "Add model" })).toBeInTheDocument();
    expect(screen.queryByText(/no model yet/)).toBeNull();
  });

  it("claims nothing about the organization when the model profiles could not be read", async () => {
    // The empty-page trap: a request that failed and an organization with no
    // model are the same empty list, and only one of them is a dead end. An
    // organization with a dozen models must not be told it has none, that its
    // agents cannot run, or that a permission is what stands in the way -
    // because `/providers/model-profiles` answered 502. The panel says what is
    // actually known, which is that the read did not land (#863).
    state.profiles = [];
    state.profilesStatus = "failed";
    await mount();

    expect(await screen.findByText("Models could not be listed")).toBeInTheDocument();
    expect(screen.queryByText(/organization has no models/)).toBeNull();
    expect(screen.queryByText(/no model yet/)).toBeNull();
  });

  it("raises nothing at all while the model profiles are still being read", async () => {
    // The cold load of the Builder, which is the ordinary path rather than an
    // event: an empty list nobody has answered for yet is neither a dead end
    // nor a failure, and a destructive panel here would fire on every first
    // paint until it stopped being read.
    state.profiles = [];
    state.profilesStatus = "pending";
    await mount();

    expect(await screen.findByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByText("Models could not be listed")).toBeNull();
    expect(screen.queryByText(/organization has no models/)).toBeNull();
    expect(screen.queryByText(/no model yet/)).toBeNull();
  });

  it("stays quiet until the caller's permissions are known", async () => {
    // `can()` answers false while the set is in flight and after it fails, so
    // claiming the caller cannot add a model before then is a claim about a
    // request rather than about them.
    state.profiles = [];
    state.permissionsLoaded = false;
    await mount();

    expect(await screen.findByText(/organization has no models/)).toBeInTheDocument();
    expect(screen.queryByText(/no model yet/)).toBeNull();
  });
});
