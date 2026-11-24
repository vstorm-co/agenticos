import { beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import {
  applyProposal,
  createEvalCase,
  createLedgerEntry,
  createProposal,
  deleteEvalCase,
  deleteLedgerEntry,
  getEvalTry,
  getLedgerEntry,
  getProposal,
  listAgentPatterns,
  listEvalCases,
  listLedgerEntries,
  listOrgPatterns,
  listProposals,
  rejectProposal,
  revertProposal,
  startEvalTry,
  trackPattern,
  updateLedgerEntry,
  type FailurePattern,
} from "./failure-learning-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const pattern = (overrides: Partial<FailurePattern> = {}): FailurePattern => ({
  agent_id: "agent-1",
  agent_name: "Helper",
  model: "anthropic:claude-sonnet-4-5",
  status: "failed",
  error_class: "ModelHTTPError:400",
  pattern_key: "failed:ModelHTTPError:400",
  count: 4,
  first_seen: "2026-11-03T00:00:00Z",
  last_seen: "2026-11-09T00:00:00Z",
  sample_run_ids: ["run-1"],
  sample_message_ids: [],
  already_tracked: false,
  ...overrides,
});

describe("failure-learning-api", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("reaches each route of the loop", async () => {
    const ledger = {
      scope: "agent" as const,
      pattern_key: "failed:ModelHTTPError:400",
      title: "Bad requests",
      summary: "The agent keeps sending bad requests.",
      evidence: {},
    };
    const evalCase = {
      name: "Refund",
      input: { message: "Refund my order" },
      expectation: { kind: "contains" as const, field: "text" as const, value: "refund" },
    };

    await listOrgPatterns();
    await listAgentPatterns("agent-1");
    await listLedgerEntries("agent-1");
    await listLedgerEntries("agent-1", "open");
    await createLedgerEntry("agent-1", ledger);
    await getLedgerEntry("agent-1", "entry-1");
    await updateLedgerEntry("agent-1", "entry-1", { status: "dismissed" });
    await deleteLedgerEntry("agent-1", "entry-1");
    await listEvalCases("agent-1");
    await createEvalCase("agent-1", evalCase);
    await deleteEvalCase("agent-1", "case-1");
    await startEvalTry("agent-1", { case_ids: ["case-1"] });
    await getEvalTry("agent-1", "try-1");
    await listProposals("agent-1");
    await listProposals("agent-1", "applied");
    await createProposal("agent-1", {
      target: { type: "instructions" },
      old_text: "old",
      new_text: "new",
      rationale: "because",
    });
    await getProposal("agent-1", "prop-1");
    await applyProposal("agent-1", "prop-1");
    await revertProposal("agent-1", "prop-1");
    await rejectProposal("agent-1", "prop-1", "not a real pattern");

    expect(apiClient.get).toHaveBeenCalledWith("/failure-learning/patterns");
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/failure-learning/patterns");
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/failure-learning/ledger", {
      params: undefined,
    });
    expect(apiClient.get).toHaveBeenCalledWith("/agents/agent-1/failure-learning/ledger", {
      params: { status: "open" },
    });
    expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-1/failure-learning/ledger", ledger);
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/ledger/entry-1",
      { status: "dismissed" },
    );
    expect(apiClient.delete).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/ledger/entry-1",
    );
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/eval-cases",
      evalCase,
    );
    expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-1/failure-learning/eval-runs", {
      case_ids: ["case-1"],
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/proposals/prop-1/apply",
    );
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/proposals/prop-1/revert",
    );
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/proposals/prop-1/reject",
      { reason: "not a real pattern" },
    );
  });

  it("reads a skill try's target and tested-text hash from the wire", async () => {
    const hash = "a".repeat(64);
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      id: "try-2",
      agent_id: "agent-1",
      proposal_id: "prop-2",
      target_skill_id: "skill-1",
      tested_content_sha256: hash,
      created_at: null,
      cases: [],
      passed: 0,
      failed: 0,
      pending: 0,
      gate_passed: null,
    });

    const read = await getEvalTry("agent-1", "try-2");

    expect(read.target_skill_id).toBe("skill-1");
    expect(read.tested_content_sha256).toBe(hash);
    expectTypeOf(read.target_skill_id).toEqualTypeOf<string | null>();
    expectTypeOf(read.tested_content_sha256).toEqualTypeOf<string | null>();
  });

  it("tracks an agent pattern under its own agent", async () => {
    await trackPattern(pattern(), { title: "Bad requests", summary: "Keeps failing." });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-1/failure-learning/ledger",
      expect.objectContaining({
        scope: "agent",
        model: "anthropic:claude-sonnet-4-5",
        pattern_key: "failed:ModelHTTPError:400",
      }),
    );
  });

  it("tracks a model pattern through its first sample run's agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ agent_id: "agent-9" });

    await trackPattern(pattern({ agent_id: null, agent_name: null }), {
      title: "Bad requests",
      summary: "Follows the model.",
    });

    expect(apiClient.get).toHaveBeenCalledWith("/runs/run-1");
    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/agent-9/failure-learning/ledger",
      expect.objectContaining({ scope: "model" }),
    );
  });

  it("refuses to track a pattern with no sample run to anchor on", async () => {
    await expect(
      trackPattern(pattern({ agent_id: null, sample_run_ids: [] }), {
        title: "Bad requests",
        summary: "Follows the model.",
      }),
    ).rejects.toThrow("no sample run");
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
