import type {
  BrowserProcedure,
  BrowserProcedureTeaching,
  BrowserProcedureTeachingReview,
  BrowserProcedureTeachingSummary,
} from "@/types/browser-procedure-teaching";
import type { Browse } from "@/lib/browse";

export const BROWSER_PROCEDURE_TEACHING_IDS = {
  owner: "11111111-1111-4111-8111-111111111111",
  org: "22222222-2222-4222-8222-222222222222",
  run: "33333333-3333-4333-8333-333333333333",
  agent: "44444444-4444-4444-8444-444444444444",
  session: "55555555-5555-4555-8555-555555555555",
  takeover: "66666666-6666-4666-8666-666666666666",
  skill: "77777777-7777-4777-8777-777777777777",
  proposal: "88888888-8888-4888-8888-888888888888",
  other: "99999999-9999-4999-8999-999999999999",
};
export function browserProcedureTeachingReviewFixture(): BrowserProcedureTeachingReview {
  return {
    name: "monthly-report",
    // i18n-exempt: a synthetic owner-authored description, never product copy.
    description: "Find and review the monthly report.",
    actions: [
      // i18n-exempt: synthetic reviewed labels supplied as API data in acceptance fixtures.
      {
        sequence: 1,
        // i18n-exempt: synthetic owner-reviewed instruction supplied as API data.
        label: "Open reports",
        path_template: "/reports",
        parameter: null,
        omit: false,
      },
      // i18n-exempt: synthetic reviewed instruction; its parameter has no captured/default value.
      {
        sequence: 2,
        // i18n-exempt: synthetic owner-reviewed instruction with no captured/default input.
        label: "Enter the report month",
        path_template: null,
        parameter: "month",
        omit: false,
      },
      // i18n-exempt: synthetic reviewed instruction supplied as API data.
      { sequence: 3, label: "Open the report", path_template: null, parameter: null, omit: false },
    ],
    // i18n-exempt: synthetic parameter description, not a value or default.
    parameters: [{ name: "month", description: "The month to review" }],
    // i18n-exempt: synthetic owner-authored procedure prerequisites.
    prerequisites: ["A person has completed any required sign-in"],
    // i18n-exempt: synthetic owner-authored success check, not verified business evidence.
    success_checks: ["Confirm that the report is for the requested month"],
  };
}
export function browserProcedureTeachingFixture(
  overrides: Partial<BrowserProcedureTeaching> = {},
): BrowserProcedureTeaching {
  return {
    id: BROWSER_PROCEDURE_TEACHING_IDS.session,
    agent_id: BROWSER_PROCEDURE_TEACHING_IDS.agent,
    run_id: BROWSER_PROCEDURE_TEACHING_IDS.run,
    call_id: "teaching-call",
    tab_id: "main",
    target_skill_id: null,
    // i18n-exempt: synthetic owner-authored capture title used only by test/visual fixtures.
    title: "Monthly report demonstration",
    allowed_origins: ["https://reports.example"],
    source: "manual",
    verified_success: false,
    status: "review",
    revision: 2,
    reason_code: null,
    events: [
      {
        sequence: 1,
        input_id: BROWSER_PROCEDURE_TEACHING_IDS.takeover,
        action: "navigate",
        origin: "https://reports.example",
        target: null,
        direction: null,
        human_step: false,
      },
      {
        sequence: 2,
        input_id: BROWSER_PROCEDURE_TEACHING_IDS.other,
        action: "input_parameter",
        origin: "https://reports.example",
        target: { role: "textbox", fingerprint: "sha256:" + "a".repeat(64) },
        direction: null,
        human_step: false,
      },
      {
        sequence: 3,
        input_id: BROWSER_PROCEDURE_TEACHING_IDS.proposal,
        action: "click",
        origin: "https://reports.example",
        target: { role: "button", fingerprint: "sha256:" + "b".repeat(64) },
        direction: null,
        human_step: false,
      },
    ],
    review: null,
    procedure: null,
    generation_state: "none",
    generation_mode: null,
    max_cost_usd: null,
    proposal_id: null,
    created_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    capture_ends_at: new Date(Date.now() + 1_800_000).toISOString(),
    ...overrides,
  };
}
export function browserProcedureTeachingSummaryFixture(
  overrides: Partial<BrowserProcedureTeaching> = {},
): BrowserProcedureTeachingSummary {
  const session = browserProcedureTeachingFixture(overrides);
  return {
    id: session.id,
    agent_id: session.agent_id,
    target_skill_id: session.target_skill_id,
    title: session.title,
    allowed_origins: session.allowed_origins,
    source: session.source,
    verified_success: session.verified_success,
    status: session.status,
    revision: session.revision,
    reason_code: session.reason_code,
    generation_state: session.generation_state,
    proposal_id: session.proposal_id,
    created_at: session.created_at,
    expires_at: session.expires_at,
    capture_ends_at: session.capture_ends_at,
  };
}
export function browserProcedureFixture(
  overrides: Partial<BrowserProcedure> = {},
): BrowserProcedure {
  const session = browserProcedureTeachingFixture();
  const review = browserProcedureTeachingReviewFixture();
  return {
    schema_version: 1,
    origins: session.allowed_origins,
    steps: session.events.map((event, index) => ({
      action: event.action,
      origin: event.origin,
      label: review.actions[index]!.label,
      role: event.target?.role ?? null,
      parameter: review.actions[index]!.parameter,
      path_template: review.actions[index]!.path_template,
      direction: event.direction,
      human_step: event.human_step,
    })),
    parameters: review.parameters,
    prerequisites: review.prerequisites,
    success_checks: review.success_checks,
    source_session_id: session.id,
    source_hash: "a".repeat(64),
    source: "manual",
    verified_success: false,
    ...overrides,
  };
}
export function browserProcedureTeachingBrowseFixture(overrides: Partial<Browse> = {}): Browse {
  return {
    runId: BROWSER_PROCEDURE_TEACHING_IDS.run,
    callId: "teaching-call",
    tabId: "main",
    heldBy: "Synthetic-owner",
    heldById: BROWSER_PROCEDURE_TEACHING_IDS.owner,
    takeoverId: BROWSER_PROCEDURE_TEACHING_IDS.takeover,
    goal: "Synthetic-demonstration",
    title: "Synthetic-reports",
    url: "https://reports.example/reports",
    steps: [],
    image: null,
    imageStep: -1,
    maxSteps: null,
    outcome: null,
    detail: null,
    ...overrides,
  };
}
