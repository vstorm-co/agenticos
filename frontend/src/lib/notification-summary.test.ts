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
