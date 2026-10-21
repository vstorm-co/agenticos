import { describe, expect, it, vi } from "vitest";

import { announceChange, onRemoteChange, staleQueries } from "./live-updates";
import { qk } from "@/lib/query-keys";
import type { ChangeEvent, ChangeResource } from "@/types/change-events";

const ORG = "org-1";

function change(resource: ChangeResource): ChangeEvent {
  return {
    organization_id: ORG,
    resource,
    id: "row-1",
    action: "updated",
    surface: "mcp",
    actor_user_id: "user-1",
    actor_name: "Ada",
    origin_tab: null,
  };
}

describe("staleQueries", () => {
  it("marks a resource's whole family stale, not only the row", () => {
    expect(staleQueries(change("organization"))).toEqual([
      qk.organizations.all(),
      qk.assistant(change("organization").organization_id),
    ]);
    expect(staleQueries(change("trigger"))).toEqual([qk.triggers.all()]);
    expect(staleQueries(change("notification"))).toEqual([qk.notifications.all()]);
    expect(staleQueries(change("run"))).toEqual([qk.runs.all(), qk.conversations.list()]);
  });

  it("refreshes the sharing panels with every row somebody can share", () => {
    expect(staleQueries(change("agent"))).toEqual([
      qk.agents.all(),
      qk.sharing.all(),
      qk.runs.assistantSignals(ORG),
    ]);
    expect(staleQueries(change("skill"))).toEqual([qk.skills.all(), qk.sharing.all()]);
    expect(staleQueries(change("context"))).toEqual([qk.context.all(), qk.sharing.all()]);
    expect(staleQueries(change("knowledge_base"))).toEqual([qk.kb.all(), qk.sharing.all()]);
    expect(staleQueries(change("artifact"))).toEqual([qk.artifacts.all(), qk.sharing.all()]);
    expect(staleQueries(change("secret"))).toEqual([qk.secrets.all(), qk.sharing.all()]);
    expect(staleQueries(change("mcp_connection"))).toEqual([
      qk.mcpConnections.all(),
      qk.sharing.all(),
    ]);
  });

  it("refreshes what the Architect may raise with runs and with agents", () => {
    // Under `runs`, so a run or an approval event reaches it through that family.
    expect(qk.runs.assistantSignals(ORG).slice(0, 1)).toEqual(qk.runs.all());
    expect(staleQueries(change("agent"))).toContainEqual(qk.runs.assistantSignals(ORG));
  });

  it("refreshes the surfaces an agent is exposed on with the channel bots", () => {
    expect(staleQueries(change("channel"))).toEqual([qk.channelBots.list(), qk.exposures.all()]);
  });

  it("refreshes a member's groups and the reader's own permissions with the member list", () => {
    expect(staleQueries(change("member"))).toEqual([
      qk.organizations.members(ORG),
      qk.organizations.groups(ORG),
      qk.organizations.permissions(ORG),
    ]);
    expect(staleQueries(change("invitation"))).toEqual([qk.invitations.list(ORG)]);
    expect(staleQueries(change("group"))).toEqual([qk.organizations.groups(ORG), qk.sharing.all()]);
  });
});

describe("onRemoteChange", () => {
  it("hands each change to every listener until it unsubscribes", () => {
    const first = vi.fn();
    const second = vi.fn();
    const stopFirst = onRemoteChange(first);
    const stopSecond = onRemoteChange(second);

    announceChange(change("agent"));
    stopFirst();
    announceChange(change("skill"));
    stopSecond();

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(2);
  });
});
