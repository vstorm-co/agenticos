import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentSpec } from "@/types/agents";
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

const state = {
  permissions: [] as Permission[],
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
        mcp_server_ids: [],
        subagents: [],
      } satisfies AgentSpec,
    },
    isLoading: false,
    saveDraft: { mutateAsync: vi.fn(), isPending: false },
    validate: { mutateAsync: vi.fn() },
    publish: { mutateAsync: vi.fn(), isPending: false },
    rollback: { mutateAsync: vi.fn() },
    setAvatar: { mutateAsync: vi.fn(), isPending: false },
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
  useCapabilityCatalog: () => ({ capabilities: [] }),
  useExposures: () => ({ exposures: [] }),
  useEmbeds: () => ({ embeds: [] }),
  useKnowledgeBases: () => ({ kbs: [] }),
  useMcpCatalog: () => ({ servers: [] }),
  useModelProviders: () => ({
    profiles: [
      {
        id: "p-1",
        label: "openai default",
        provider: "openai",
        model: "gpt-5",
        secret_id: "s-1",
      },
    ],
    deleteProfile: { mutate: vi.fn() },
    createProfile: { mutateAsync: vi.fn(), isPending: false },
    catalog: [],
  }),
  useOrgMcpConnections: () => ({ connections: [] }),
  usePermissions: () => ({
    can: (permission: Permission) => state.permissions.includes(permission),
  }),
  useProviderModels: () => ({ models: [], source: null, isLoading: false }),
  useRuns: () => ({ runs: [] }),
  useSecretPurposes: () => ({ purposes: [] }),
  useSecrets: () => ({ secrets: [] }),
  useSkills: () => ({ skills: [], total: 0 }),
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
});
