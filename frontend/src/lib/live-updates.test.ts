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
    expect(staleQueries(change("agent"))).toEqual([qk.agents.all()]);
    expect(staleQueries(change("skill"))).toEqual([qk.skills.all()]);
    expect(staleQueries(change("context"))).toEqual([qk.context.all()]);
    expect(staleQueries(change("knowledge_base"))).toEqual([qk.kb.all()]);
    expect(staleQueries(change("artifact"))).toEqual([qk.artifacts.all()]);
    expect(staleQueries(change("organization"))).toEqual([qk.organizations.all()]);
  });

  it("refreshes a member's groups and the reader's own permissions with the member list", () => {
    expect(staleQueries(change("member"))).toEqual([
      qk.organizations.members(ORG),
      qk.organizations.groups(ORG),
      qk.organizations.permissions(ORG),
    ]);
    expect(staleQueries(change("invitation"))).toEqual([qk.invitations.list(ORG)]);
    expect(staleQueries(change("group"))).toEqual([qk.organizations.groups(ORG)]);
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
