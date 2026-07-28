import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAgent, useAgents, useCapabilityCatalog } from "./use-agents";
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
  mcp_server_ids: [],
  budget: null,
};

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
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

    expect(await result.current.validate()).toEqual([]);
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

    expect(await result.current.validate()).toEqual([
      "Unknown capability: typo",
      "No model selected",
    ]);
  });

  it("falls back to the error message when the server sends no problem list", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", draft_spec: {} });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Service unavailable"));

    const { result } = renderHook(() => useAgent("a1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(await result.current.validate()).toEqual(["Service unavailable"]);
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

    expect(await result.current.validate()).toEqual(["You cannot edit this agent"]);
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
