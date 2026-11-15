import type {
  AgentAuthoring,
  AuthoringRequest,
  ContextChange,
  Hunk,
  SuggestionBatch,
} from "@/types/authoring";

export function hunk(overrides: Partial<Hunk> = {}): Hunk {
  return {
    id: "hunk-1",
    kind: "instructions",
    origin: "improve",
    status: "pending",
    // i18n-exempt: fixture text a test asserts on, not copy
    old_text: "Be brief.",
    // i18n-exempt: fixture text a test asserts on, not copy
    new_text: "Be brief. Refunds take 30 days.",
    accepted_text: null,
    // i18n-exempt: fixture text a test asserts on, not copy
    context_before: "You answer refunds.\n",
    context_after: "",
    capability_id: null,
    tool_id: null,
    base_name: null,
    base_description: null,
    path: null,
    op: null,
    base_value: null,
    new_value: null,
    accepted_value: null,
    effect: null,
    names: {},
    blocked: null,
    expected_effect: "",
    new_name: null,
    new_description: null,
    // i18n-exempt: fixture text a test asserts on, not copy
    rationale: "Readers corrected the refund window.",
    // i18n-exempt: fixture text a test asserts on, not copy
    evidence: [{ run_id: "run-0123456789", quote: "You said 90 days" }],
    evidence_dropped: 0,
    applies: true,
    decided_at: null,
    ...overrides,
  };
}

export function batch(overrides: Partial<SuggestionBatch> = {}): SuggestionBatch {
  return {
    id: "batch-1",
    agent_id: "agent-1",
    status: "open",
    // i18n-exempt: fixture text a test asserts on, not copy
    expected_effect: "Refund answers name 30 days",
    request_id: "request-1",
    hunks: [hunk()],
    check_eval_run_ids: [],
    created_at: "2026-10-21T10:00:00Z",
    ...overrides,
  };
}

export function authoringRequest(overrides: Partial<AuthoringRequest> = {}): AuthoringRequest {
  return {
    id: "request-1",
    kind: "improve",
    target: "agent",
    agent_id: "agent-1",
    skill_id: null,
    status: "completed",
    error: null,
    estimate_usd: "0.04",
    cost_usd: "0.03",
    run_ids: ["improver-run"],
    window_days: 30,
    evidence: { runs: 22, rated_down: 6 },
    report: null,
    created_at: "2026-10-21T10:00:00Z",
    started_at: "2026-10-21T10:00:01Z",
    finished_at: "2026-10-21T10:01:00Z",
    ...overrides,
  };
}

export function agentAuthoring(overrides: Partial<AgentAuthoring> = {}): AgentAuthoring {
  return { batch: batch(), latest: authoringRequest(), verify: null, ...overrides };
}

export function contextChange(overrides: Partial<ContextChange> = {}): ContextChange {
  return {
    id: "change-1",
    context_id: "ctx-1",
    context_name: "house-style",
    // i18n-exempt: fixture text a test asserts on, not copy
    description: "How we write.",
    // i18n-exempt: fixture text a test asserts on, not copy
    content: "Write in plain words. Sign as the team.",
    // i18n-exempt: fixture text a test asserts on, not copy
    current_description: "How we write.",
    // i18n-exempt: fixture text a test asserts on, not copy
    current_content: "Write in plain words.",
    status: "pending",
    decided_by_user_id: null,
    decided_at: null,
    stale: false,
    rationale: "",
    evidence: [],
    evidence_dropped: 0,
    expected_effect: "",
    authoring_request_id: "request-1",
    used_by: [{ id: "agent-1", name: "Clerk" }],
    created_at: "2026-10-21T10:00:00Z",
    updated_at: null,
    revision: 1,
    reaches: [],
    reaches_hidden: 0,
    ...overrides,
  };
}
