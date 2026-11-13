import { expect, it } from "vitest";
import type { Notification } from "@/lib/notifications-api";
import { notificationSummary } from "./notification-summary";

const t = (key: string, values?: Record<string, string | number>) =>
  values ? `${key}(${Object.values(values).join(",")})` : key;
const stop = (key: string) => `stop:${key}`;
const AGENT = {
  id: "a1",
  slug: "refunds",
  name: "Refund desk",
  has_avatar: false,
  avatar_color: null,
};

function row(event_type: string, outcome: Notification["outcome"], agent = AGENT): Notification {
  return {
    id: "n1",
    event_type,
    summary: "server summary",
    context_url: null,
    read_at: null,
    created_at: "2026-10-26T10:00:00Z",
    agent,
    outcome,
  };
}

it("words a finished improvement with its reason, without internal codes", () => {
  expect(
    notificationSummary(row("improvement_finished", { status: "ready", reason: null }), t, stop),
  ).toBe("outcome.improvement.ready(Refund desk)");
  expect(
    notificationSummary(
      row("improvement_finished", { status: "stopped", reason: "budget" }),
      t,
      stop,
    ),
  ).toBe("outcome.improvement.stopped(Refund desk) stop:budget");
  expect(
    notificationSummary(
      row("improvement_finished", { status: "failed", reason: "brand_new" }),
      t,
      stop,
    ),
  ).toBe("outcome.improvement.failed(Refund desk)");
  expect(
    notificationSummary(row("improvement_finished", { status: "stopped", reason: null }), t, stop),
  ).toBe("outcome.improvement.stopped(Refund desk)");
});

it("words finished tests and question writing", () => {
  expect(
    notificationSummary(
      row("eval_run_finished", { status: "budget_exceeded", reason: null }),
      t,
      stop,
    ),
  ).toBe("outcome.test.budget_exceeded");
  expect(
    notificationSummary(
      row("case_generation_finished", { status: "ready", reason: null }),
      t,
      stop,
    ),
  ).toBe("outcome.questions.ready");
});

it("keeps the server's summary for anything it cannot word", () => {
  for (const item of [
    row("improvement_finished", null),
    row("improvement_finished", { status: "accepted", reason: null }),
    { ...row("improvement_finished", { status: "ready", reason: null }), agent: null },
    row("eval_run_finished", { status: "running", reason: null }),
    row("case_generation_finished", { status: "running", reason: null }),
    row("approval_requested", { status: "pending", reason: null }),
  ])
    expect(notificationSummary(item, t, stop)).toBe("server summary");
});

it("says which step a session stopped at for a person, from its stage or its reason", () => {
  const waiting = (outcome: Partial<NonNullable<Notification["outcome"]>>) =>
    notificationSummary(
      row("improvement_finished", { status: "waiting", reason: null, ...outcome }),
      t,
      stop,
    );
  expect(waiting({ stage: "classifying" })).toBe(
    "outcome.improvement.waiting.understand(Refund desk)",
  );
  expect(waiting({ stage: "analyzing" })).toBe(
    "outcome.improvement.waiting.understand(Refund desk)",
  );
  expect(waiting({ stage: "filtering" })).toBe("outcome.improvement.waiting.changes(Refund desk)");
  expect(waiting({ reason: "filtering" })).toBe("outcome.improvement.waiting.changes(Refund desk)");
  expect(
    waiting({ reason: "filtering", next_step_blocked: { reason: "missing_holdout", needed: 2 } }),
  ).toBe("outcome.improvement.waiting.blocked(Refund desk,2)");
  expect(
    notificationSummary(
      row(
        "improvement_finished",
        { status: "waiting", reason: null, stage: "filtering" },
        {
          ...AGENT,
          name: "",
        },
      ),
      t,
      stop,
    ),
  ).toBe("server summary");
});

it("words an attempt that did not do better as finished, not stopped", () => {
  expect(
    notificationSummary(
      row("improvement_finished", { status: "stopped", reason: "no_change" }),
      t,
      stop,
    ),
  ).toBe("outcome.improvement.attemptFinished(Refund desk) stop:no_change");
});

it("words a session nobody took further, which closed on its own", () => {
  expect(
    notificationSummary(
      row("improvement_finished", { status: "stale", reason: "expired" }),
      t,
      stop,
    ),
  ).toBe("outcome.improvement.stopped(Refund desk) stop:expired");
});

function worded(event_type: string, params: Notification["params"]): Notification {
  return { ...row(event_type, null), params };
}

it("words an approval request and a budget stop from their values, in the reader's language", () => {
  expect(
    notificationSummary(worded("approval_requested", { agent_name: "Memory probe" }), t, stop),
  ).toBe("kind.approvalRequested(Memory probe)");
  expect(
    notificationSummary(
      worded("budget_exceeded", {
        agent_name: "Probe agent",
        scope: "agent",
        limit_usd: "0.0005",
        spent_usd: "0.0008",
      }),
      t,
      stop,
    ),
  ).toBe("kind.budgetExceeded(Probe agent,agent,,$0.0008,$0.0005)");
  expect(
    notificationSummary(
      worded("budget_warning", { group_name: "Sales", share: "82", limit: "100.00" }),
      t,
      stop,
    ),
  ).toBe("kind.budgetWarning(Sales,82,$100.00)");
});

it("names the department whose budget stopped a run", () => {
  expect(
    notificationSummary(
      worded("budget_exceeded", {
        agent_name: "Probe",
        scope: "group",
        subject: "Sales",
        limit_usd: "10",
        spent_usd: "10.02",
      }),
      t,
      stop,
    ),
  ).toBe("kind.budgetExceeded(Probe,department,Sales,$10.0200,$10.00)");
});

it("shows a limit to the cent, and below a cent to the place spend is shown at", () => {
  const stopped = (limit: string) =>
    notificationSummary(
      worded("budget_exceeded", {
        agent_name: "Probe",
        scope: "organization",
        limit_usd: limit,
        spent_usd: "20.01",
      }),
      t,
      stop,
    );
  expect(stopped("20")).toBe("kind.budgetExceeded(Probe,organization,,$20.0100,$20.00)");
  expect(stopped("0.004")).toBe("kind.budgetExceeded(Probe,organization,,$20.0100,$0.0040)");
});

it("keeps the server's sentence where it kept no values, or for a kind the console does not word", () => {
  expect(notificationSummary(worded("budget_exceeded", null), t, stop)).toBe("server summary");
  expect(notificationSummary(worded("run_failed", { agent_name: "Probe" }), t, stop)).toBe(
    "server summary",
  );
});

it("keeps the metered spend precision above a cent", () => {
  expect(
    notificationSummary(
      worded("budget_exceeded", {
        agent_name: "Probe",
        scope: "agent",
        limit_usd: "0.01",
        spent_usd: "0.0101",
      }),
      t,
      stop,
    ),
  ).toBe("kind.budgetExceeded(Probe,agent,,$0.0101,$0.01)");
});
