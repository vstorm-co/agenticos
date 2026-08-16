import { describe, expect, it } from "vitest";

import { toMapDelegates } from "./agent-map-tree";
import type { DelegationTreeNode } from "@/types/agents";

const t = (key: string) => key;

function node(overrides: Partial<DelegationTreeNode> = {}): DelegationTreeNode {
  return {
    key: "delegate:a2:0",
    kind: "delegate",
    status: "ok",
    agent_id: "a2",
    name: "Researcher",
    mode: null,
    pinned_version: 1,
    stale: false,
    truncated: false,
    children: [],
    ...overrides,
  };
}

describe("toMapDelegates", () => {
  it("keys each node by its path, so one delegate under two parents stays two nodes", () => {
    const first = toMapDelegates(
      [node({ children: [node({ key: "delegate:a3:0", agent_id: "a3", name: "Editor" })] })],
      t,
      "delegate:a2:0",
    )[0]!;

    expect(first.key).toBe("delegate:a2:0/delegate:a2:0");
    expect(first.children?.[0]?.key).toBe("delegate:a2:0/delegate:a2:0/delegate:a3:0");
  });

  it("links a resolved delegate to its own page and nothing else", () => {
    const converted = toMapDelegates(
      [node(), node({ key: "delegate:a4:1", agent_id: "a4", status: "cycle" })],
      t,
      "root",
    );

    expect(converted[0]!.href).toBe("/agents/a2");
    expect(converted[0]!.problem).toBeUndefined();
    expect(converted[1]!.href).toBeUndefined();
    expect(converted[1]!.problem).toBe("cycle");
  });

  it("names a restricted node as an agent you cannot see", () => {
    // The server refuses to say - deliberately, so a parent's map cannot probe
    // private agents - and the map must not render an empty chip for it.
    const restricted = toMapDelegates([node({ status: "restricted", name: null })], t, "root")[0]!;

    expect(restricted.name).toBe("delegateUnreachable");
    expect(restricted.problem).toBe("restricted");
  });

  it("carries staleness and the depth cap, and drops their false halves", () => {
    const converted = toMapDelegates(
      [node({ stale: true, truncated: true }), node({ key: "delegate:a5:1", agent_id: "a5" })],
      t,
      "root",
    );

    expect(converted[0]!.stale).toBe(true);
    expect(converted[0]!.truncated).toBe(true);
    expect(converted[1]!.stale).toBeUndefined();
    expect(converted[1]!.truncated).toBeUndefined();
    expect(converted[1]!.children).toBeUndefined();
  });

  it("converts a specialist without inventing a page for it", () => {
    const specialist = toMapDelegates(
      [
        node({
          key: "specialist:0",
          kind: "specialist",
          agent_id: null,
          name: "summariser",
          mode: "async",
          pinned_version: null,
        }),
      ],
      t,
      "root",
    )[0]!;

    expect(specialist.kind).toBe("specialist");
    expect(specialist.name).toBe("summariser");
    expect(specialist.mode).toBe("async");
    expect(specialist.href).toBeUndefined();
  });
});
