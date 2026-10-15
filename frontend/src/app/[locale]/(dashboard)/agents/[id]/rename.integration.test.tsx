import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AgentBuilderPage from "./page";
import type { AgentDetail } from "@/types/agents";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * Renaming an agent in the Builder.
 *
 * A duplicate arrives as "<name> (copy)", and the name is spec, so the field
 * edits the draft and the draft's autosave is what stores it. The refusal is a
 * blank name: the spec rejects it, so it must never reach the save.
 */

const AGENT: AgentDetail = {
  id: "a1",
  slug: "support",
  name: "Support (copy)",
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
    name: "Support (copy)",
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
// One instance across renders, so the call the autosave makes can be read back.
const saveDraft = mutation();

vi.mock("@/hooks", () => ({
  useAgent: () => ({
    agent: AGENT,
    isLoading: false,
    saveDraft,
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

const PARAMS = Promise.resolve({ id: "a1", locale: "en" });

async function mount() {
  await act(async () => {
    render(<AgentBuilderPage params={PARAMS} />, { wrapper });
    await PARAMS;
  });
}

// Past the Builder's 1.2s autosave debounce.
async function settleAutosave() {
  await act(async () => {
    vi.advanceTimersByTime(1500);
  });
}

describe("renaming an agent in the Builder", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("stores a new name and description with the draft", async () => {
    allowed = new Set([Perm.agentsEdit]);
    await mount();
    const name = await screen.findByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("Support (copy)");

    vi.useFakeTimers();
    fireEvent.change(name, { target: { value: "Support - Norway" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "Answers Norwegian customers" },
    });
    await settleAutosave();

    expect(saveDraft.mutateAsync).toHaveBeenCalledTimes(1);
    expect(saveDraft.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Support - Norway",
        description: "Answers Norwegian customers",
      }),
    );
  });

  it("clears a description to null rather than an empty string", async () => {
    allowed = new Set([Perm.agentsEdit]);
    await mount();
    const description = await screen.findByRole("textbox", { name: "Description" });

    vi.useFakeTimers();
    fireEvent.change(description, { target: { value: "x" } });
    fireEvent.change(description, { target: { value: "" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Renamed" },
    });
    await settleAutosave();

    expect(saveDraft.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Renamed", description: null }),
    );
  });

  it("refuses a blank name without sending it", async () => {
    allowed = new Set([Perm.agentsEdit]);
    await mount();
    const name = await screen.findByRole("textbox", { name: "Name" });

    vi.useFakeTimers();
    fireEvent.change(name, { target: { value: "   " } });
    await settleAutosave();

    expect(screen.getByText("An agent needs a name.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(saveDraft.mutateAsync).not.toHaveBeenCalled();
  });

  it("holds Publish back while the name is blank", async () => {
    allowed = new Set([Perm.agentsEdit, Perm.agentsPublish]);
    await mount();
    const name = await screen.findByRole("textbox", { name: "Name" });
    const publish = screen.getByRole("button", { name: "Publish" });
    expect(publish).toBeEnabled();

    fireEvent.change(name, { target: { value: "   " } });

    expect(publish).toBeDisabled();
    fireEvent.click(publish);
    expect(saveDraft.mutateAsync).not.toHaveBeenCalled();
  });

  it("shows the name read-only to a caller who may not edit", async () => {
    allowed = new Set([Perm.agentsView]);
    await mount();

    expect(await screen.findByRole("textbox", { name: "Name" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Description" })).toBeDisabled();
  });
});
