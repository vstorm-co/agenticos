import { describe, expect, it } from "vitest";

import { agentTag, filterAgentRows, myAgentsPolicy } from "./my-agents";
import { Perm, type Permission } from "@/types/permissions";

const holds =
  (...held: Permission[]) =>
  (permission: Permission) =>
    held.includes(permission);

const ME = "user-1";
const mine = { id: "a1", owner_user_id: ME };
const shared = { id: "a2", owner_user_id: "user-2" };
const ownerless = { id: "a3", owner_user_id: null };

describe("myAgentsPolicy", () => {
  it("a builder sees everything the card can do", () => {
    const policy = myAgentsPolicy(holds(Perm.agentsEdit, Perm.runsView, Perm.agentsRun));

    expect(policy).toEqual({ includeOwn: true, showRunCounts: true, showOpenChat: true });
  });

  it("a viewer gets the shared list with no counts and no chat button", () => {
    const policy = myAgentsPolicy(holds(Perm.agentsView));

    expect(policy).toEqual({ includeOwn: false, showRunCounts: false, showOpenChat: false });
  });

  it("a member chats but never sees run counts", () => {
    const policy = myAgentsPolicy(holds(Perm.agentsView, Perm.agentsEdit, Perm.agentsRun));

    expect(policy).toEqual({ includeOwn: true, showRunCounts: false, showOpenChat: true });
  });
});

describe("agentTag", () => {
  it("mine is yours, everything else is shared", () => {
    expect(agentTag(mine, ME)).toBe("yours");
    expect(agentTag(shared, ME)).toBe("shared");
    expect(agentTag(ownerless, ME)).toBe("shared");
  });

  it("with no signed-in id nothing is yours", () => {
    expect(agentTag(mine, null)).toBe("shared");
  });
});

describe("filterAgentRows", () => {
  it("without agents:edit only the shared rows remain", () => {
    const rows = filterAgentRows([mine, shared, ownerless], myAgentsPolicy(holds()), ME);

    expect(rows.map((row) => row.id)).toEqual(["a2", "a3"]);
  });

  it("with agents:edit the caller's own rows stay", () => {
    const rows = filterAgentRows([mine, shared], myAgentsPolicy(holds(Perm.agentsEdit)), ME);

    expect(rows.map((row) => row.id)).toEqual(["a1", "a2"]);
  });
});
