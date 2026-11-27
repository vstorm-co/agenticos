import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import type { Translate } from "@/lib/agent-step-captions";

import { usd, wordedSummary } from "./notification-wording";

function translator(locale: string, messages: object): Translate {
  const t = createTranslator({ locale, messages, namespace: "notifications" } as never) as (
    key: string,
    values?: Record<string, string | number>,
  ) => string;
  return (key, values) => t(key, values);
}

const english = translator("en", en);

const say = (params: Record<string, string>, t: Translate = english) => wordedSummary(params, t);

describe("wordedSummary", () => {
  it("words a run and a routine, with and without what they said", () => {
    expect(say({ wording: "run_completed", agent_name: "Clerk" })).toBe("Clerk finished a run.");
    expect(say({ wording: "routine_finished", routine_name: "Digest" })).toBe("Digest finished.");
    expect(say({ wording: "routine_finished", routine_name: "Digest", excerpt: "All quiet" })).toBe(
      "Digest: All quiet",
    );
    expect(say({ wording: "answered_while_away", agent_name: "Clerk" })).toBe(
      "Clerk answered while you were away.",
    );
    expect(say({ wording: "answer_failed", agent_name: "Clerk", error: "Timed out" })).toBe(
      "Clerk could not finish its answer: Timed out",
    );
    expect(say({ wording: "run_failed", agent_name: "Clerk" })).toBe("Clerk's run failed.");
    expect(say({ wording: "run_failed", agent_name: "Clerk", error: "Out of budget" })).toBe(
      "Clerk's run failed: Out of budget",
    );
  });

  it("words a routine held on its budget, named or not", () => {
    expect(
      say({ wording: "routine_budget_paused", routine_kind: "watch", limit: "5", spent: "5.2" }),
    ).toBe(
      "Your routine is waiting: your monthly proactive-work budget of $5.00 is used up " +
        "($5.20 spent). Ask an administrator to review the limit or wait for the next month " +
        "to resume.",
    );
    expect(
      say({
        wording: "routine_budget_paused",
        routine_name: "Digest",
        routine_kind: "trigger",
        limit: "0.004",
        spent: "0.005",
      }),
    ).toContain("Digest is waiting: its monthly routine budget of $0.0040");
  });

  it("words a routine needing attention by its code, and counts an automatic stop", () => {
    expect(
      say({
        wording: "routine_blocked",
        routine_name: "Digest",
        routine_detail: "watch_auto_stopped",
        failures: "3",
      }),
    ).toBe(
      "Digest needs attention: Paused automatically after 3 unsuccessful checks. " +
        "Review Activity and resume when ready.",
    );
    expect(say({ wording: "routine_blocked", routine_detail: "chat_unavailable" })).toBe(
      "Your routine needs attention: Its answer is in Activity, but its chosen chat is unavailable.",
    );
    expect(say({ wording: "routine_blocked", routine_detail: "brand_new" })).toBeNull();
  });

  it("words requests, suggestions, briefings and sharing", () => {
    expect(
      say({
        wording: "capability_requested",
        requester_name: "Ann",
        capability_name: "Web search",
        agent_name: "Clerk",
        reason: "for prices",
      }),
    ).toBe("Ann asked for Web search in Clerk: for prices");
    expect(say({ wording: "suggestions_ready", count: "1" })).toBe(
      "AgenticOS has a new suggestion for you.",
    );
    expect(say({ wording: "briefing", count: "2" })).toBe("Your watches found 2 new things.");
    expect(say({ wording: "resource_shared", resource_name: "Q3", group_name: "Sales" })).toBe(
      "“Q3” was shared with Sales.",
    );
    expect(
      say({
        wording: "invitation_received",
        inviter_name: "Ann",
        organization_name: "Acme",
        role: "member",
      }),
    ).toBe("Ann invited you to join Acme as member.");
    expect(say({ wording: "conversation_shared", shared_by: "Ann" })).toBe(
      "Ann shared a conversation with you.",
    );
    expect(
      say({ wording: "conversation_shared", shared_by: "Ann", conversation_title: "Q3" }),
    ).toBe("Ann shared “Q3” with you.");
  });

  it("words a room mention and a thread reply", () => {
    expect(say({ wording: "room_mention", sender: "Alex", title: "Design" })).toBe(
      "Alex mentioned you in Design",
    );
    expect(say({ wording: "room_thread_reply", sender: "Alex", title: "Design" })).toBe(
      "Alex replied in a thread in Design",
    );
  });

  it("words ingestion and syncs", () => {
    expect(say({ wording: "ingestion_failed", filename: "a.pdf", error_message: "Empty" })).toBe(
      "“a.pdf” failed to ingest: Empty",
    );
    expect(
      say({
        wording: "sync_completed",
        collection_name: "Handbook",
        ingested: "3",
        updated: "1",
        skipped: "0",
        removed: "0",
        failed: "2",
      }),
    ).toBe("Sync of “Handbook” finished: 3 ingested, 1 updated, 0 skipped, 0 removed, 2 failed.");
    expect(say({ wording: "sync_failed", collection_name: "", error: "Refused" })).toBe(
      "Sync of a source with no collection failed: Refused",
    );
    expect(say({ wording: "sync_failed", collection_name: "Handbook", error: "Refused" })).toBe(
      "Sync of “Handbook” failed: Refused",
    );
  });

  it("words pages changing version and owner", () => {
    expect(
      say({ wording: "artifact_version_published", artifact_title: "Board", version: "4" }),
    ).toBe("“Board” has a new version (v4).");
    expect(say({ wording: "artifact_owner_given", by_name: "Ann", title: "Board" })).toBe(
      "Ann made you the owner of Board. Its data stays hidden from others until you confirm it.",
    );
    expect(
      say({
        wording: "artifact_owner_taken",
        by_name: "Ann",
        title: "Board",
        new_owner_name: "Bo",
      }),
    ).toBe("Ann made Bo the owner of Board.");
  });

  it("words MCP servers going down and coming back", () => {
    expect(say({ wording: "mcp_server_down", server_name: "Linear" })).toContain(
      "The MCP server Linear stopped answering.",
    );
    expect(say({ wording: "mcp_server_recovered", server_name: "Linear" })).toBe(
      "The MCP server Linear is answering again.",
    );
  });

  it("words eval suites, their verdicts and each threshold reason", () => {
    expect(
      say({
        wording: "eval_suite_reevaluated",
        suite_name: "Refunds",
        agent_name: "Clerk",
        previous_verdict: "failed",
        status: "something_new",
      }),
    ).toBe("Refunds on Clerk: failed → something_new after review. Promotion requires a person.");
    const reasons = [
      { code: "pass_rate_below", value: 0.4, limit: 0.8 },
      { code: "nothing_graded" },
      { code: "regressions", value: 1 },
      { code: "cost_per_pass_rise", value: 0.5 },
      { code: "cost_per_pass_rise", value: 0, detail: "zero_baseline" },
      { code: "p95_rise", value: 0.25 },
      { code: "p95_rise", detail: "zero_baseline" },
      { code: "ungraded", value: 2 },
      { code: "incomplete", value: 1 },
      { code: "crashed", value: 3 },
      { code: "invalid_comparison" },
    ];
    expect(
      say({
        wording: "eval_suite_failed",
        suite_name: "Refunds",
        agent_name: "Clerk",
        version: "7",
        status: "failed",
        reasons: JSON.stringify(reasons),
        cases: "'Where is it?'",
        more_cases: "2",
      }),
    ).toBe(
      "Refunds failed on Clerk v7: pass rate 40% is below 80%; no case could be graded; " +
        "1 case breaks reproducibly; cost per passed case rose 50%; cost per passed case rose " +
        "from zero, exceeding every percentage ceiling; p95 latency rose 25%; p95 latency rose " +
        "from zero, exceeding every percentage ceiling; 2 cases nothing grades; 1 case the " +
        "provider or a scorer failed on; the agent's run failed on 3 cases; the comparison is " +
        "invalid. Failing: 'Where is it?' and 2 more.",
    );
    expect(
      say({
        wording: "eval_suite_failed",
        suite_name: "Refunds",
        agent_name: "Clerk",
        status: "inconclusive",
        reasons: "[]",
        cases: "'Where is it?'",
      }),
    ).toBe("Refunds could not decide on Clerk: below its threshold. Undecided: 'Where is it?'.");
    expect(
      say({
        wording: "eval_suite_failed",
        suite_name: "Refunds",
        agent_name: "Clerk",
        status: "passed",
        reasons: "[]",
      }),
    ).toBe("Refunds could not decide on Clerk: below its threshold.");
    for (const reasons of ["not json", "{}"])
      expect(say({ wording: "eval_suite_failed", reasons })).toBeNull();
  });

  it("words a promotion past a gate and a shared change", () => {
    expect(
      say({
        wording: "promotion_overridden",
        version: "3",
        agent_name: "Clerk",
        environment_name: "production",
        suite_names: "Refunds, Tone",
        reason: "Hotfix",
      }),
    ).toBe("v3 of Clerk went to production without passing Refunds, Tone: Hotfix");
    expect(
      say({ wording: "shared_change_applied", kind: "context", name: "FAQ", agent_name: "Clerk" }),
    ).toBe("A change to the context file FAQ went live for Clerk");
    expect(say({ wording: "shared_change_applied", kind: "skill", agent_name: "Clerk" })).toBe(
      "A change to a skill it reads went live for Clerk",
    );
  });

  it("words administration notices, and an action it has no sentence for by its name", () => {
    expect(say({ wording: "security_event", action: "secret.rotated" })).toBe(
      "A vault secret was rotated.",
    );
    expect(say({ wording: "security_event", action: "admin.unknown" })).toBe(
      "A privileged action was recorded: admin.unknown",
    );
    expect(
      say({ wording: "background_task_paused", kind: "ingest", reason: "it kept failing" }),
    ).toBe(
      "Background jobs of the kind ingest are paused: it kept failing. Resume them on the " +
        "Background jobs page once the cause is fixed.",
    );
    expect(
      say({
        wording: "background_task_paused",
        kind: "ingest",
        organization_name: "Acme",
        reason: "it kept failing",
      }),
    ).toContain("are paused for Acme: it kept failing.");
    expect(say({ wording: "configuration_changed" })).toBe(
      "The deployment's settings were updated.",
    );
    expect(say({ wording: "usage_report", org_name: "Acme" })).toBe("Usage report for Acme");
    expect(say({ wording: "agent_usage_report", agent_name: "Clerk" })).toBe(
      "Usage report for Clerk",
    );
    expect(say({ wording: "coalesced", coalesced: "configuration_changed" })).toContain(
      "changed more times in one minute",
    );
    expect(say({ wording: "coalesced", coalesced: "something_new" })).toBeNull();
  });

  it("words a log alert over minutes or hours", () => {
    const alert = { wording: "workflow_log_alert", rule_name: "Errors", workflow_name: "Intake" };
    expect(say({ ...alert, count: "3", window_minutes: "180" })).toBe(
      "Errors: 3 occurrences in the log of Intake in the last 3 hours.",
    );
    expect(say({ ...alert, count: "1", window_minutes: "15" })).toBe(
      "Errors: 1 occurrence in the log of Intake in the last 15 minutes.",
    );
  });

  it("keeps the English summary for a wording it does not know", () => {
    expect(say({ wording: "something_new" })).toBeNull();
  });
});

describe("every sentence", () => {
  const rows: Record<string, string>[] = [
    { wording: "routine_blocked", routine_detail: "trigger_auto_stopped", failures: "2" },
    { wording: "routine_budget_paused", routine_kind: "watch", limit: "5", spent: "5" },
    { wording: "suggestions_ready", count: "3" },
    { wording: "briefing", count: "1" },
    { wording: "sync_failed", collection_name: "", error: "x" },
    { wording: "conversation_shared", shared_by: "Ann", conversation_title: "Q3" },
    {
      wording: "invitation_received",
      inviter_name: "Ann",
      organization_name: "Acme",
      role: "member",
    },
    { wording: "room_mention", sender: "Alex", title: "Design" },
    { wording: "room_thread_reply", sender: "Alex", title: "Design" },
    { wording: "shared_change_applied", kind: "context", name: "FAQ", agent_name: "Clerk" },
    { wording: "background_task_paused", kind: "k", organization_name: "Acme", reason: "r" },
    {
      wording: "workflow_log_alert",
      rule_name: "R",
      count: "2",
      workflow_name: "W",
      window_minutes: "60",
    },
    {
      wording: "eval_suite_failed",
      suite_name: "S",
      agent_name: "A",
      version: "1",
      status: "failed",
      reasons: JSON.stringify([
        { code: "pass_rate_below", value: 0.5, limit: 0.9 },
        { code: "pass_rate_below", value: 0.5 },
      ]),
      cases: "'q'",
      more_cases: "0",
    },
  ];

  it("words each sentence without falling back to its key", () => {
    const t = english;
    for (const row of rows) {
      const said = wordedSummary(row, t);
      expect(said).toBeTruthy();
      expect(said).not.toContain("notifications.");
      expect(said).not.toContain("{");
    }
  });
});

it("says a limit below a cent as it is", () => {
  expect(usd("0.0005")).toBe("$0.0005");
  expect(usd("20")).toBe("$20.00");
});
