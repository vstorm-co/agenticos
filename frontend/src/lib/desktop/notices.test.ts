import { describe, expect, it } from "vitest";

import type { Notification } from "@/lib/notifications-api";
import type { ToolApproval } from "@/types/runs";

import {
  argumentsPreview,
  newApprovals,
  newestOf,
  newNotifications,
  notificationPath,
} from "./notices";

const approval = (id: string, status: ToolApproval["status"] = "pending") =>
  ({
    id,
    status,
    run_id: "r",
    agent_id: "a",
    tool_id: "send_email",
    tool_args: {},
  }) as unknown as ToolApproval;

const row = (created_at: string, extra: Partial<Notification> = {}): Notification => ({
  id: created_at,
  event_type: "run_completed",
  summary: "Done",
  context_url: "/runs/1",
  read_at: null,
  created_at,
  ...extra,
});

describe("newApprovals", () => {
  it("is what is pending now and was not before", () => {
    const fresh = newApprovals(new Set(["a"]), [
      approval("a"),
      approval("b"),
      approval("c", "approved"),
    ]);
    expect(fresh.map((a) => a.id)).toEqual(["b"]);
  });
});

describe("newNotifications", () => {
  it("is every unread row when nothing had been seen - an inbox that was empty at the first look", () => {
    expect(newNotifications(null, [row("2026-10-21T10:00:00Z")])).toHaveLength(1);
  });

  it("is the unread rows after the newest seen, oldest first, without approval requests", () => {
    const rows = [
      row("2026-10-21T10:03:00Z"),
      row("2026-10-21T10:02:00Z"),
      row("2026-10-21T10:01:30Z", { read_at: "2026-10-21T10:02:00Z" }),
      row("2026-10-21T10:01:45Z", { event_type: "approval_requested" }),
      row("2026-10-21T09:00:00Z"),
    ];
    expect(newNotifications("2026-10-21T10:00:00Z", rows).map((r) => r.created_at)).toEqual([
      "2026-10-21T10:02:00Z",
      "2026-10-21T10:03:00Z",
    ]);
  });
});

describe("newestOf", () => {
  it("is the newest creation time, or what was known before", () => {
    expect(newestOf(null, [])).toBeNull();
    expect(newestOf("2026-01-01", [row("2026-02-01"), row("2025-12-01")])).toBe("2026-02-01");
    expect(newestOf("2026-03-01", [row("2026-02-01")])).toBe("2026-03-01");
  });
});

describe("argumentsPreview", () => {
  it("shows every argument, cut when long rather than left out", () => {
    expect(argumentsPreview({ to: "a@b.c", count: 2, flags: ["x"] })).toBe(
      'to: a@b.c, count: 2, flags: ["x"]',
    );
    const long = argumentsPreview({ body: "x".repeat(400) });
    expect(long).toHaveLength(160);
    expect(long.endsWith("…")).toBe(true);
  });
});

describe("notificationPath", () => {
  it("opens the row's own page on the console, and the dashboard otherwise", () => {
    expect(notificationPath(row("t"))).toBe("/runs/1");
    expect(notificationPath(row("t", { context_url: null }))).toBe("/dashboard");
    expect(notificationPath(row("t", { context_url: "https://evil.example/" }))).toBe("/dashboard");
  });
});
