import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import {
  useAgent,
  useAgentVersion,
  useAgentVersions,
  useAgents,
  useCapabilityCatalog,
  useDelegationTree,
} from "./use-agents";
import { useAgentEnvironments } from "./use-agent-environments";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { AgentSpec } from "@/types/agents";

const SPEC: AgentSpec = {
  spec_version: 3,
  name: "Support",
  description: null,
  instructions: "",
  model_profile_id: null,
  model_settings: {},
  capabilities: [],
  collection_ids: [],
  skill_ids: [],
  context_ids: [],
  mcp_server_ids: [],
  budget: null,
};

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    upload: vi.fn(),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useAgents", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the agents the caller can see", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "a1", slug: "support", name: "Support", status: "published" }],
      total: 1,
    });
    const { result } = renderHook(() => useAgents(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.agents).toHaveLength(1);
  });

  it("posts a whole spec when creating", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "a1", name: "Support" });

    const { result } = renderHook(() => useAgents(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.create.mutateAsync(SPEC);

    expect(apiClient.post).toHaveBeenCalledWith("/agents", {
      // Whatever version was read round-trips; the client never authors one.
      spec: expect.objectContaining({ name: "Support", spec_version: 3 }),
    });
  });
});

describe("useAgent draft", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends every per-tool decision to the server exactly as the Builder set it", async () => {
    // The spec is PUT whole, so nothing here picks fields - which is precisely
    // why a field added to the spec can go missing without anything failing.
    // A tool held for approval that arrives at the server unheld is the whole
    // feature quietly not existing.
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: SPEC });
    vi.mocked(apiClient.put).mockResolvedValue({ id: "a1", name: "Support" });

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.saveDraft.mutateAsync({
      ...SPEC,
      capabilities: [
        {
          id: "email",
          config: {},
          approval: "never",
          tool_approval: { send_email: "required" },
          tool_overrides: { send_email: { name: "send_invoice_email" } },
          secret_id: "sec-1",
          enabled: true,
        },
      ],
    });

    expect(apiClient.put).toHaveBeenCalledWith("/agents/a1/draft", {
      spec: expect.objectContaining({
        capabilities: [
          expect.objectContaining({
            approval: "never",
            tool_approval: { send_email: "required" },
            tool_overrides: { send_email: { name: "send_invoice_email" } },
            // A dropped secret reference is a capability that fails at run time
            // holding a credential the organization did select.
            secret_id: "sec-1",
          }),
        ],
      }),
    });
  });
});

describe("useAgent validation", () => {
  beforeEach(() => vi.clearAllMocks());

  it("returns an empty list when the draft is publishable", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.post).mockResolvedValue(undefined);

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(await result.current.validate()).toEqual({ problems: [], fields: [] });
  });

  it("returns every problem rather than throwing", async () => {
    // A rejected draft is a normal state while editing. Fixing a form one
    // error per round trip is the difference between a Builder people use and
    // one they avoid.
    //
    // Rejecting with a real `ApiError` carrying the real envelope is what makes
    // this test worth having. It used to reject with `{details: {problems}}` -
    // a shape nothing produces - and so it passed for months against a hook
    // that read a property `ApiError` does not have and threw the list away.
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "This agent cannot be published yet", {
        error: {
          code: "BAD_REQUEST",
          message: "This agent cannot be published yet",
          details: { problems: ["Unknown capability: typo", "No model selected"] },
        },
      }),
    );

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(await result.current.validate()).toEqual({
      problems: ["Unknown capability: typo", "No model selected"],
      fields: [],
    });
  });

  it("carries the inputs a refused capability configuration named", async () => {
    // The half that says *which box to fix*. Publish validation aggregates
    // every problem in a spec into sentences, and it used to keep only the
    // sentence for a refused config - so `default_top_k: 999` reached the
    // Builder as one line about the capability and marked nothing (#882).
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "This agent cannot be published yet", {
        error: {
          code: "BAD_REQUEST",
          message: "This agent cannot be published yet",
          details: {
            problems: ["Capability 'knowledge': Invalid configuration for capability 'knowledge'"],
            fields: [
              {
                field: "capabilities.knowledge.config.default_top_k",
                message: "Input should be less than or equal to 50",
              },
            ],
          },
        },
      }),
    );

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const refusal = await result.current.validate();
    expect(refusal.fields).toEqual([
      {
        field: "capabilities.knowledge.config.default_top_k",
        message: "Input should be less than or equal to 50",
      },
    ]);
    // And still as a line, because most of a spec is not a generated form.
    expect(refusal.problems).toHaveLength(1);
  });

  it("falls back to the error message when the server sends no problem list", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Service unavailable"));

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(await result.current.validate()).toEqual({
      problems: ["Service unavailable"],
      fields: [],
    });
  });

  it("does not turn a refused permission into a list of spec problems", async () => {
    // A 403 says the caller may not validate, not that the draft is wrong.
    // Rendering it in the "cannot be published yet" banner would blame the
    // agent for something the reader cannot fix by editing it.
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(403, "You cannot edit this agent", {
        error: {
          code: "AUTHORIZATION_ERROR",
          message: "You cannot edit this agent",
          details: null,
        },
      }),
    );

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(await result.current.validate()).toEqual({
      problems: ["You cannot edit this agent"],
      fields: [],
    });
  });

  it("does not fetch until an agent is selected", () => {
    renderHook(() => useAgent(null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("useAgent rollback", () => {
  beforeEach(() => vi.clearAllMocks());

  it("publishes a new version rather than moving a pointer backwards", async () => {
    // History stays linear: the timeline shows that a rollback happened rather
    // than pretending the bad version never existed.
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "v3", version: 3 });

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.rollback.mutateAsync("v1");

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/rollback", { version_id: "v1" });
  });
});

describe("useAgent avatar colour", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends the chosen slot to the agent's colour endpoint", async () => {
    // A column, not the spec: it patches the row directly, like the picture.
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "a1", avatar_color: 3 });

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.setColor.mutateAsync(3);

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/avatar-color", { color: 3 });
  });

  it("reports a failed colour change rather than swallowing it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("nope"));

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.setColor.mutateAsync(null)).rejects.toThrow();
  });
});

describe("useCapabilityCatalog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the catalog the Builder renders", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "knowledge", name: "Knowledge search", category: "knowledge" }],
      total: 1,
    });
    const { result } = renderHook(() => useCapabilityCatalog(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.capabilities[0]?.id).toBe("knowledge");
  });
});

/**
 * The mutation callbacks.
 *
 * Each one invalidates the agent cache and then says something. They look like
 * boilerplate and are not: `create` is the only mutation here that deliberately
 * does **not** toast its failure, because the things that stop an agent being
 * created are things the dialog can fix in place - and a toast would put the
 * message somewhere it cannot be acted on and then take it away.
 */
describe("useAgents mutations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("says what was created, by name", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "a1", name: "Support" });
    const { result } = renderHook(() => useAgents(), { wrapper });

    await result.current.create.mutateAsync(SPEC);

    expect(toast.success).toHaveBeenCalledWith("Created Support");
  });

  it("leaves a failed creation to the dialog rather than toasting it", async () => {
    // The regression this guards: a toast here duplicates the field-level
    // message the dialog already shows, in a place nobody can act on.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("handle taken"));
    const { result } = renderHook(() => useAgents(), { wrapper });

    await expect(result.current.create.mutateAsync(SPEC)).rejects.toThrow("handle taken");

    expect(toast.error).not.toHaveBeenCalled();
  });

  it("says a clone is a draft, because nothing was published", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "a2", name: "Support copy" });
    const { result } = renderHook(() => useAgents(), { wrapper });

    await result.current.clone.mutateAsync("a1");

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/clone", {});
    expect(toast.success).toHaveBeenCalledWith(
      "Created Support copy - a draft, nothing published yet",
    );
  });

  it("reports a failed clone", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useAgents(), { wrapper });

    await expect(result.current.clone.mutateAsync("a1")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("nope");
  });

  it("sends the specialist and its model fallback when promoting", async () => {
    // The specialist whole, and the model a null profile falls back to - the
    // surface handles the toast, so the hook only carries the request.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "a2", name: "invoice-parser" });
    const specialist = {
      name: "invoice-parser",
      description: "Pulls line items out of an invoice",
      instructions: "Read the invoice.",
      model_profile_id: null,
      model_settings: {},
      capabilities: [],
      collection_ids: [],
      skill_ids: [],
      context_ids: [],
      max_steps: null,
      preferred_mode: null,
    };
    const { result } = renderHook(() => useAgents(), { wrapper });

    await result.current.promote.mutateAsync({ specialist, fallbackModelProfileId: "m1" });

    expect(apiClient.post).toHaveBeenCalledWith("/agents/promote", {
      specialist,
      fallback_model_profile_id: "m1",
    });
  });

  it("says archiving keeps the history", async () => {
    // The one thing somebody hesitating over the button wants to know.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "a1" });
    const { result } = renderHook(() => useAgents(), { wrapper });

    await result.current.archive.mutateAsync("a1");

    expect(toast.success).toHaveBeenCalledWith("Agent archived. Its history and runs are kept.");
  });

  it("reports a failed archive", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("busy"));
    const { result } = renderHook(() => useAgents(), { wrapper });

    await expect(result.current.archive.mutateAsync("a1")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("busy");
  });

  it("says a restored agent is live when it went back to published", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ name: "Support", status: "published" });
    const { result } = renderHook(() => useAgents(), { wrapper });

    await result.current.unarchive.mutateAsync("a1");

    expect(toast.success).toHaveBeenCalledWith("Support is live again");
  });

  it("says a restored agent needs publishing when it came back a draft", async () => {
    // Unarchiving does not publish, and telling somebody it is "live again" when
    // it answers nothing would be the wrong half of the truth.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ name: "Support", status: "draft" });
    const { result } = renderHook(() => useAgents(), { wrapper });

    await result.current.unarchive.mutateAsync("a1");

    expect(toast.success).toHaveBeenCalledWith("Support is back as a draft - publish it to run it");
  });

  it("reports a failed restore", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("gone"));
    const { result } = renderHook(() => useAgents(), { wrapper });

    await expect(result.current.unarchive.mutateAsync("a1")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("gone");
  });

  it("deletes an agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useAgents(), { wrapper });

    await result.current.remove.mutateAsync("a1");

    expect(apiClient.delete).toHaveBeenCalledWith("/agents/a1");
    expect(toast.success).toHaveBeenCalledWith("Agent deleted");
  });

  it("reports a failed delete", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("in use"));
    const { result } = renderHook(() => useAgents(), { wrapper });

    await expect(result.current.remove.mutateAsync("a1")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("in use");
  });
});

describe("useAgent mutations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("saves a draft without announcing it", async () => {
    // Autosave: a toast on every keystroke-debounce would be unusable.
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1" });
    vi.mocked(apiClient.put).mockResolvedValue({ id: "a1" });
    const { result } = renderHook(() => useAgent("a1"), { wrapper });

    await result.current.saveDraft.mutateAsync(SPEC);

    expect(toast.success).not.toHaveBeenCalled();
  });

  it("reports a failed autosave, because the work is at risk", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1" });
    vi.mocked(apiClient.put).mockRejectedValue(new Error("conflict"));
    const { result } = renderHook(() => useAgent("a1"), { wrapper });

    await expect(result.current.saveDraft.mutateAsync(SPEC)).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("conflict");
  });

  it("names the version it published", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1" });
    vi.mocked(apiClient.post).mockResolvedValue({ version: 4 });
    const { result } = renderHook(() => useAgent("a1"), { wrapper });

    await result.current.publish.mutateAsync("A note");

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/publish", { note: "A note" });
    expect(toast.success).toHaveBeenCalledWith("Published v4");
  });

  it("refetches the environments after a publish, because the default one moved", async () => {
    // The environments cache is not under `qk.agents`, so the shared
    // invalidation never reaches it - and a panel still naming the old pin
    // right after publishing is the publish dialog's sentence contradicted.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const shared = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ version: 4 });
    const { result } = renderHook(
      () => ({ agent: useAgent("a1"), environments: useAgentEnvironments("a1") }),
      { wrapper: shared },
    );
    await waitFor(() => expect(result.current.environments.isLoading).toBe(false));
    const fetches = () =>
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/agents/a1/environments")
        .length;
    const before = fetches();

    await result.current.agent.publish.mutateAsync(null);

    await waitFor(() => expect(fetches()).toBeGreaterThan(before));
  });

  it("reports a refused publish", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1" });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("spec invalid"));
    const { result } = renderHook(() => useAgent("a1"), { wrapper });

    await expect(result.current.publish.mutateAsync(null)).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("spec invalid");
  });

  it("reports a failed rollback", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1" });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("no such version"));
    const { result } = renderHook(() => useAgent("a1"), { wrapper });

    await expect(result.current.rollback.mutateAsync("v9")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("no such version");
  });

  it("uploads an avatar and says so", async () => {
    // Not part of the spec, so it takes effect at once rather than at publish.
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1" });
    vi.mocked(apiClient.upload).mockResolvedValue({ id: "a1" });
    const file = new File(["x"], "face.png", { type: "image/png" });
    const { result } = renderHook(() => useAgent("a1"), { wrapper });

    await result.current.setAvatar.mutateAsync(file);

    expect(apiClient.upload).toHaveBeenCalledWith("/agents/a1/avatar", file);
    expect(toast.success).toHaveBeenCalledWith("Avatar updated");
  });

  it("reports a rejected avatar", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1" });
    vi.mocked(apiClient.upload).mockRejectedValue(new Error("too large"));
    const { result } = renderHook(() => useAgent("a1"), { wrapper });

    await expect(
      result.current.setAvatar.mutateAsync(new File(["x"], "face.png")),
    ).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("too large");
  });
});

/**
 * The version timeline, and one version's frozen spec.
 *
 * Two queries rather than one: the timeline is read every time the history opens
 * and a spec is the whole configuration of an agent, so specs are fetched per
 * version - and cached for the session, because a published version never
 * changes.
 */
describe("an agent's versions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the timeline for one agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "v1", version: 1 }], total: 1 });

    const { result } = renderHook(() => useAgentVersions("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Fifty by default, because two of the three callers are pickers - which
    // version to pin an environment or a delegate to - and a picker that offers
    // ten of sixty hides the one somebody is looking for.
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/versions", {
      params: { skip: "0", limit: "50" },
    });
    expect(result.current.versions).toHaveLength(1);
    expect(result.current.total).toBe(1);
  });

  it("asks for the page the history card is showing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 60 });

    const { result } = renderHook(() => useAgentVersions("a1", { skip: 10, limit: 10 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/versions", {
      params: { skip: "10", limit: "10" },
    });
    // Every version, not the length of this page: the listing used to report
    // its own cap, so ten versions were unreachable and nothing said so.
    expect(result.current.total).toBe(60);
  });

  it("does not fetch a timeline before an agent is chosen", () => {
    renderHook(() => useAgentVersions(null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("fetches one version's spec on its own endpoint", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "v1", version: 1, spec: SPEC });

    const { result } = renderHook(() => useAgentVersion("a1", "v1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/versions/v1");
    expect(result.current.version?.spec.name).toBe("Support");
  });

  it("does not fetch a spec until both the agent and the version are known", () => {
    // The diff mounts with one side unchosen; a request for
    // `/agents/a1/versions/null` would answer 404 and read as a deleted version.
    renderHook(() => useAgentVersion("a1", null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("hands back the failure rather than an empty spec", async () => {
    // The history renders "pick two versions" for an unresolved side, which is
    // only truthful if the caller can tell a refusal from a pending fetch.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Version not found"));

    const { result } = renderHook(() => useAgentVersion("a1", "v9"), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.version).toBeUndefined();
  });
});

describe("the delegation tree", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the tree from its own endpoint", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ truncated: true, nodes: [] });

    const { result } = renderHook(() => useDelegationTree("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/delegation-tree");
    expect(result.current.tree?.truncated).toBe(true);
  });

  it("does not walk the tree while nothing shows it", () => {
    // The server resolves and access-checks every pinned version to answer
    // this; the map dialog is the one caller, so a closed dialog costs nothing.
    renderHook(() => useDelegationTree("a1", { enabled: false }), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("does not fetch before an agent is chosen", () => {
    renderHook(() => useDelegationTree(null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("hands back the failure so the map can say the tree is partial", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useDelegationTree("a1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.tree).toBeNull();
  });
});
