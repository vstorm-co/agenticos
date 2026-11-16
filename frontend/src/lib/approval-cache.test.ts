import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import type { Outcome } from "@/lib/outcomes-api";
import { clearApprovalNotice } from "./approval-cache";
import { qk } from "./query-keys";

function notice(run: string, kind = "approval_requested"): Outcome {
  return {
    id: `${run}-${kind}`,
    kind,
    summary: "Waiting",
    context_url: null,
    status: "open",
    source_run_id: run,
    source_conversation_id: "chat",
    created_at: "2026-11-13T12:00:00Z",
    settled_at: null,
    settled_via: null,
  };
}

describe("acknowledged approval notices", () => {
  it("removes only the acknowledged run's approval and preserves other work", async () => {
    const client = new QueryClient();
    const key = qk.outcomes.conversation("chat");
    client.setQueryData(key, [notice("one"), notice("two"), notice("one", "budget_warning")]);
    await clearApprovalNotice(client, "chat", "one");
    expect(client.getQueryData(key)).toEqual([notice("two"), notice("one", "budget_warning")]);
    await clearApprovalNotice(client, "chat", "one");
    expect(client.getQueryData<Outcome[]>(key)).toHaveLength(2);
  });
  it("does not invent cache rows or modify a conversation that is not open", async () => {
    const client = new QueryClient();
    await clearApprovalNotice(client, null, "one");
    await clearApprovalNotice(client, "absent", "one");
    expect(client.getQueryData(qk.outcomes.conversation("absent"))).toBeUndefined();
  });
});
