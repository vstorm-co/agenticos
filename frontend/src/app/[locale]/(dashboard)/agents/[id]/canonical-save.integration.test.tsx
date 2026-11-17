import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, useSyncExternalStore } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import { ApiError } from "@/lib/api-error";
import type { AgentSpec, AgentDraftUpdate } from "@/types/agents";
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

const refetchAgent = vi.hoisted(() => vi.fn());
const refetchProfiles = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
const saveDraft = vi.hoisted(() =>
  vi.fn<(update: AgentDraftUpdate) => Promise<{ draft_spec: AgentSpec; draft_revision: string }>>(),
);

/** The stored draft the page reads, replaced by what the server answers after each save. */
const store = vi.hoisted(() => {
  let draft: AgentSpec | null = null;
  const listeners = new Set<() => void>();
  return {
    get: () => draft,
    set: (next: AgentSpec) => {
      draft = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
});

const state = {
  permissions: [] as Permission[],
  profiles: [MODEL_PROFILE] as (typeof MODEL_PROFILE)[],
  // Both queries settle successfully by default; a case that wants the failed
  // or still-pending read says so, because that is where an empty list stops
  // meaning "the organization has none".
  profilesStatus: "loaded" as ProfilesStatus,
  permissionsLoaded: true,
  saving: false,
  versions: [] as { version: number }[],
  nextPublished: 1,
  // This caller's access to this agent, which the page reads rather than the role.
  access: { can_edit: true, can_publish: false },
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
        ...state.access,
        draft_revision: "base",
        draft_spec: useSyncExternalStore(store.subscribe, store.get),
      },
      isLoading: false,
      refetch: refetchAgent,
      saveDraft: { mutateAsync: saveDraft, isPending: state.saving },
      validate: async () => ({ problems: [], fields: [], fixes: [] }),
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
    useDraftBase: () => ({ base: undefined }),
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
    useProviderModels: () => ({ models: [], refused: [], source: null, isLoading: false }),
    useRuns: () => ({ runs: [] }),
    useSecretPurposes: () => ({ purposes: [] }),
    useSecrets: () => ({ secrets: [] }),
    useSkills: () => ({ skills: [], total: 0 }),
  };
});

// The page's eval parts read their own queries; this test is not about them.
vi.mock("@/hooks/use-eval-runs", () => ({
  useDraftEvalRuns: () => ({ runs: [] }),
  useEvalArmSpec: () => ({ spec: undefined }),
  useRunsADataset: () => false,
}));
vi.mock("@/components/evals/draft-eval-note", () => ({ DraftEvalNote: () => null }));
vi.mock("@/components/evals/evals-panel", () => ({ EvalsPanel: () => null }));
vi.mock("@/components/authoring/assistant-strip", () => ({ AssistantStrip: () => null }));
vi.mock("@/components/evals/start-eval-dialog", () => ({ StartEvalDialog: () => null }));
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
// Only what the page tells the test panel: whether the draft is still saving.
vi.mock("@/components/agents/test-panel/test-panel", () => ({
  TestPanel: ({ saving }: { saving: boolean }) => (
    <p data-testid="test-panel">saving={String(saving)}</p>
  ),
}));

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

/** Postgres JSONB's key order, which is what a stored draft comes back in: shorter keys first, then by bytes. */
function jsonbOrder(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(jsonbOrder);
  if (value === null || typeof value !== "object") return value;
  const size = (key: string) => new TextEncoder().encode(key).length;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([a], [b]) => size(a) - size(b) || (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, inner]) => [key, jsonbOrder(inner)]),
  );
}

const INITIAL: AgentSpec = {
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
  output_schema: null,
};

async function chooseStructuredAnswers() {
  await userEvent.click(await screen.findByRole("combobox", { name: "It answers" }));
  await userEvent.click(await screen.findByRole("option", { name: "With structured data" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  refetchAgent.mockReset();
  state.permissions = [Perm.agentsEdit];
  state.access = { can_edit: true, can_publish: false };
  state.saving = false;
  state.profiles = [MODEL_PROFILE];
  state.profilesStatus = "loaded";
  state.permissionsLoaded = true;
  store.set(structuredClone(INITIAL));
  // The test panel open, so the page renders what it tells it.
  window.localStorage.setItem(
    "agenticos:test-panel:a-1",
    JSON.stringify({ open: true, mode: "draft" }),
  );
});

function serverDraft(spec: AgentSpec): AgentSpec {
  const schema = jsonbOrder(spec.output_schema);
  if (schema !== null && (typeof schema !== "object" || Array.isArray(schema)))
    throw new Error("Expected an answer schema");
  return {
    ...structuredClone(spec),
    output_schema: schema === null ? null : Object.fromEntries(Object.entries(schema)),
  };
}

describe("canonical draft acknowledgements", () => {
  it("saves a reordered schema once and releases the draft test panel", async () => {
    saveDraft.mockImplementation(async ({ spec }) => {
      const stored = serverDraft(spec);
      store.set(stored);
      return { draft_spec: stored, draft_revision: "saved" };
    });
    await mount();
    await chooseStructuredAnswers();
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1), { timeout: 6000 });
    await waitFor(() => expect(screen.queryByText("Unsaved")).toBeNull());
    expect(screen.getByTestId("test-panel")).toHaveTextContent("saving=false");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
    });
    expect(saveDraft).toHaveBeenCalledTimes(1);
  }, 15000);

  it("adopts server defaults and normalized values after its own save", async () => {
    saveDraft.mockImplementation(async ({ spec }) => {
      const stored = {
        ...serverDraft(spec),
        variables:
          spec.variables?.map((variable) => ({
            ...variable,
            description: variable.description ?? null,
          })) ?? [],
      };
      store.set(stored);
      return { draft_spec: stored, draft_revision: "saved" };
    });
    await mount();
    await chooseStructuredAnswers();
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1), { timeout: 6000 });
    await waitFor(() => expect(screen.queryByText("Unsaved")).toBeNull());
    expect(screen.getByTestId("test-panel")).toHaveTextContent("saving=false");
  }, 15000);

  it("keeps edits typed while an earlier save is awaiting its acknowledgement", async () => {
    let acknowledge:
      ((saved: { draft_spec: AgentSpec; draft_revision: string }) => void) | undefined;
    saveDraft.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    saveDraft.mockImplementation(async ({ spec }) => {
      const saved = serverDraft(spec);
      store.set(saved);
      return { draft_spec: saved, draft_revision: "saved" };
    });
    await mount();
    await chooseStructuredAnswers();
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1), { timeout: 6000 });
    const sent = saveDraft.mock.calls[0]?.[0];
    if (!sent || !acknowledge) throw new Error("No pending save");
    const title = await screen.findByText("Name and description");
    const section = title.closest("[data-tour='agent-identity']");
    if (!(section instanceof HTMLElement)) throw new Error("Missing identity section");
    const input = within(section).getByRole("textbox", { name: "Name" });
    await userEvent.clear(input);
    await userEvent.type(input, "Newer name");
    const saved = serverDraft(sent.spec);
    await act(async () => {
      store.set(saved);
      acknowledge?.({ draft_spec: saved, draft_revision: "saved" });
    });
    expect(input).toHaveValue("Newer name");
    await waitFor(
      () =>
        expect(saveDraft).toHaveBeenLastCalledWith(
          expect.objectContaining({
            spec: expect.objectContaining({ name: "Newer name" }),
            expected_revision: "saved",
          }),
        ),
      { timeout: 6000 },
    );
    await waitFor(() => expect(screen.queryByText("Unsaved")).toBeNull());
  }, 15000);
});

it("keeps its base revision after an unannounced refetch and holds edits until reload", async () => {
  state.access.can_publish = true;
  const newer = { ...INITIAL, description: "Changed in another tab" };
  saveDraft.mockRejectedValue(
    new ApiError(409, "Stale draft", {
      error: { code: "CONFLICT", message: "Stale draft", details: { reason: "draft_changed" } },
    }),
  );
  refetchAgent.mockResolvedValueOnce({
    data: { draft_spec: INITIAL, draft_revision: "base" },
    error: new Error("Offline"),
  });
  refetchAgent.mockResolvedValue({
    data: { draft_spec: newer, draft_revision: "newer" },
  });
  await mount();
  await act(async () => store.set(newer));
  const title = await screen.findByText("Name and description");
  const section = title.closest("[data-tour='agent-identity']");
  if (!(section instanceof HTMLElement)) throw new Error("Missing identity section");
  const name = within(section).getByRole("textbox", { name: "Name" });
  await userEvent.clear(name);
  await userEvent.type(name, "My local edit");
  await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1), { timeout: 6000 });
  expect(saveDraft).toHaveBeenCalledWith({
    spec: expect.objectContaining({ name: "My local edit", description: null }),
    expected_revision: "base",
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("saving is paused");
  expect(name).toHaveValue("My local edit");
  await userEvent.type(name, " still here");
  await act(async () => new Promise((resolve) => setTimeout(resolve, 1500)));
  expect(saveDraft).toHaveBeenCalledTimes(1);
  expect(name).toHaveValue("My local edit still here");
  expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Publish" }));
  expect(saveDraft).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Reload latest draft" }));
  await waitFor(() => expect(refetchAgent).toHaveBeenCalledTimes(1));
  expect(name).toHaveValue("My local edit still here");
  expect(screen.getByRole("alert")).toHaveTextContent("saving is paused");
  await userEvent.click(screen.getByRole("button", { name: "Reload latest draft" }));
  await waitFor(() => expect(name).toHaveValue(INITIAL.name));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(within(section).getByRole("textbox", { name: "Description" })).toHaveValue(
    "Changed in another tab",
  );
  expect(saveDraft).toHaveBeenCalledTimes(1);
  saveDraft.mockImplementation(async ({ spec }) => {
    store.set(spec);
    return { draft_spec: spec, draft_revision: "saved-after-reload" };
  });
  await userEvent.type(name, " revised");
  await waitFor(
    () =>
      expect(saveDraft).toHaveBeenLastCalledWith({
        spec: expect.objectContaining({
          name: `${INITIAL.name} revised`,
          description: newer.description,
        }),
        expected_revision: "newer",
      }),
    { timeout: 6000 },
  );
}, 15000);

it("disables Publish while an autosave is pending", async () => {
  state.access.can_publish = true;
  state.saving = true;
  await mount();
  expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  expect(saveDraft).not.toHaveBeenCalled();
});
