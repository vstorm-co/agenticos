import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentSpec } from "@/types/agents";
import type { ProfilesStatus } from "@/hooks/use-model-providers";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * Renaming an agent in the Builder.
 *
 * A duplicate arrives as "<name> (copy)", and the name is spec, so the field
 * edits the draft and the draft's autosave is what stores it. The refusal is a
 * blank name: the spec rejects it, so it must never reach the save.
 *
 * The harness is the first-publish spec's.
 */

const MODEL_PROFILE = {
  id: "p-1",
  label: "openai default",
  provider: "openai",
  model: "gpt-5",
  secret_id: "s-1",
};

const refetchProfiles = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const saveDraft = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

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
        slug: "support",
        name: "Support (copy)",
        status: "draft",
        has_avatar: false,
        draft_spec: {
          name: "Support (copy)",
          description: null,
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
      saveDraft: { mutateAsync: saveDraft, isPending: false },
      validate: async () => ({ problems: [], fields: [] }),
      publish: {
        mutateAsync: vi.fn().mockResolvedValue({ version: state.nextPublished }),
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

/** The name and description card: the page has other fields called "Name". */
async function identity() {
  const title = await screen.findByText("Name and description");
  return within(title.closest("[data-tour='agent-identity']") as HTMLElement);
}

// Past the Builder's 1.2s autosave debounce.
async function settleAutosave() {
  await act(async () => {
    vi.advanceTimersByTime(1500);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.permissions = [Perm.agentsEdit];
  state.versions = [];
  state.profiles = [MODEL_PROFILE];
  state.profilesStatus = "loaded";
  state.permissionsLoaded = true;
});

afterEach(() => vi.useRealTimers());

describe("renaming an agent in the Builder", () => {
  it("stores a new name and description with the draft", async () => {
    await mount();
    const card = await identity();
    const name = card.getByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("Support (copy)");

    vi.useFakeTimers();
    fireEvent.change(name, { target: { value: "Support - Norway" } });
    fireEvent.change(card.getByRole("textbox", { name: "Description" }), {
      target: { value: "Answers Norwegian customers" },
    });
    await settleAutosave();

    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(saveDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Support - Norway",
        description: "Answers Norwegian customers",
      }),
    );
  });

  it("clears a description to null rather than an empty string", async () => {
    await mount();
    const card = await identity();
    const description = card.getByRole("textbox", { name: "Description" });

    vi.useFakeTimers();
    fireEvent.change(description, { target: { value: "x" } });
    fireEvent.change(description, { target: { value: "" } });
    fireEvent.change(card.getByRole("textbox", { name: "Name" }), {
      target: { value: "Renamed" },
    });
    await settleAutosave();

    expect(saveDraft).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Renamed", description: null }),
    );
  });

  it("refuses a blank name without sending it", async () => {
    await mount();
    const card = await identity();
    const name = card.getByRole("textbox", { name: "Name" });

    vi.useFakeTimers();
    fireEvent.change(name, { target: { value: "   " } });
    await settleAutosave();

    expect(screen.getByText("An agent needs a name.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(saveDraft).not.toHaveBeenCalled();
  });

  it("holds Publish back while the name is blank", async () => {
    state.permissions = [Perm.agentsEdit, Perm.agentsPublish];
    await mount();
    const card = await identity();
    const name = card.getByRole("textbox", { name: "Name" });
    const publish = screen.getByRole("button", { name: "Publish" });
    expect(publish).toBeEnabled();

    fireEvent.change(name, { target: { value: "   " } });

    expect(publish).toBeDisabled();
  });

  it("shows the name read-only to a caller who may not edit", async () => {
    state.permissions = [Perm.agentsView];
    await mount();
    const card = await identity();

    expect(card.getByRole("textbox", { name: "Name" })).toBeDisabled();
    expect(card.getByRole("textbox", { name: "Description" })).toBeDisabled();
  });
});
