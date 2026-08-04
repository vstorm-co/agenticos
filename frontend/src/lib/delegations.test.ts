import { describe, expect, it } from "vitest";

import { applyDelegationFrame, childrenOf, closeOpenDelegations, rootsOf } from "./delegations";
import type { Delegation, SubagentFrame } from "@/types";

/** A `subagent_start`, which is the only frame that can create a panel. */
function start(
  taskId: string,
  options: { subagent?: string; depth?: number; mode?: "sync" | "async"; prompt?: string } = {},
): SubagentFrame {
  return {
    kind: "subagent_start",
    task_id: taskId,
    subagent: options.subagent ?? "researcher",
    depth: options.depth ?? 0,
    mode: options.mode ?? "sync",
    prompt: options.prompt ?? "find three papers",
  };
}

function finished(
  taskId: string,
  options: Partial<Omit<Extract<SubagentFrame, { kind: "subagent_complete" }>, "kind">> = {},
): SubagentFrame {
  return {
    kind: "subagent_complete",
    task_id: taskId,
    subagent: "researcher",
    depth: 0,
    status: "completed",
    run_id: null,
    cost_usd: null,
    input_tokens: null,
    output_tokens: null,
    error: null,
    ...options,
  };
}

/** Every frame in order, the way the socket delivers them. */
function fold(frames: SubagentFrame[], from: Delegation[] = []): Delegation[] {
  return frames.reduce(applyDelegationFrame, from);
}

function named(delegations: Delegation[], taskId: string): Delegation {
  const found = delegations.find((delegation) => delegation.taskId === taskId);
  if (found === undefined) throw new Error(`no delegation ${taskId}`);
  return found;
}

describe("applyDelegationFrame - keeping concurrent specialists apart", () => {
  it("gives every delegation its own panel, in the order they started", () => {
    // The whole reason the contract carries a task id: three specialists
    // generating at once produce one unreadable paragraph without it.
    const delegations = fold([
      start("t1", { subagent: "researcher" }),
      start("t2", { subagent: "writer" }),
      start("t3", { subagent: "critic" }),
    ]);

    expect(delegations.map((delegation) => delegation.subagent)).toEqual([
      "researcher",
      "writer",
      "critic",
    ]);
  });

  it("routes each delta to the delegation that produced it", () => {
    const delegations = fold([
      start("t1", { subagent: "researcher" }),
      start("t2", { subagent: "writer" }),
      { kind: "subagent_text_delta", task_id: "t2", subagent: "writer", depth: 0, delta: "Once " },
      {
        kind: "subagent_text_delta",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        delta: "found ",
      },
      {
        kind: "subagent_text_delta",
        task_id: "t2",
        subagent: "writer",
        depth: 0,
        delta: "upon a time",
      },
    ]);

    expect(named(delegations, "t1").text).toBe("found ");
    expect(named(delegations, "t2").text).toBe("Once upon a time");
  });

  it("keeps a delegate's reasoning apart from its answer", () => {
    const delegations = fold([
      start("t1"),
      {
        kind: "subagent_thinking_delta",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        delta: "three sources ",
      },
      {
        kind: "subagent_thinking_delta",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        delta: "should do",
      },
      { kind: "subagent_text_delta", task_id: "t1", subagent: "researcher", depth: 0, delta: "ok" },
    ]);

    expect(named(delegations, "t1").thinking).toBe("three sources should do");
    expect(named(delegations, "t1").text).toBe("ok");
  });

  it("starts a delegation open, because no frame says it is running", () => {
    expect(fold([start("t1")])[0]!.status).toBe("running");
  });

  it("keeps the first start when one arrives twice", () => {
    // A task id is unique per delegation, so a repeat is a repeat - and replacing
    // the panel would discard whatever had already streamed into it.
    const delegations = fold([
      start("t1"),
      { kind: "subagent_text_delta", task_id: "t1", subagent: "researcher", depth: 0, delta: "hi" },
      start("t1", { prompt: "something else" }),
    ]);

    expect(delegations).toHaveLength(1);
    expect(delegations[0]!.text).toBe("hi");
    expect(delegations[0]!.prompt).toBe("find three papers");
  });
});

describe("applyDelegationFrame - a delegate's own tool calls", () => {
  it("opens a row for a call and marks it when its result lands", () => {
    const delegations = fold([
      start("t1"),
      {
        kind: "subagent_tool_call",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "search_documents",
        tool_call_id: "c1",
      },
      {
        kind: "subagent_tool_result",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "search_documents",
        tool_call_id: "c1",
        ok: true,
      },
    ]);

    expect(named(delegations, "t1").steps).toEqual([
      { id: "c1", name: "search_documents", ok: true },
    ]);
  });

  it("records a tool that raised as having failed rather than as still running", () => {
    const delegations = fold([
      start("t1"),
      {
        kind: "subagent_tool_call",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "fetch_url",
        tool_call_id: "c1",
      },
      {
        kind: "subagent_tool_result",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "fetch_url",
        tool_call_id: "c1",
        ok: false,
      },
    ]);

    expect(named(delegations, "t1").steps[0]!.ok).toBe(false);
  });

  it("leaves a call with no result yet unresolved", () => {
    const delegations = fold([
      start("t1"),
      {
        kind: "subagent_tool_call",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "ls",
        tool_call_id: "c1",
      },
    ]);

    expect(named(delegations, "t1").steps[0]!.ok).toBeNull();
  });

  it("marks only the call the result belongs to", () => {
    // A delegate with two calls in flight: resolving both on one result would show
    // work as finished that is still running.
    const delegations = fold([
      start("t1"),
      {
        kind: "subagent_tool_call",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "ls",
        tool_call_id: "c1",
      },
      {
        kind: "subagent_tool_call",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "grep",
        tool_call_id: "c2",
      },
      {
        kind: "subagent_tool_result",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "grep",
        tool_call_id: "c2",
        ok: true,
      },
    ]);

    expect(named(delegations, "t1").steps.map((step) => step.ok)).toEqual([null, true]);
  });

  it("does not open a second row for a call id it already has", () => {
    const call: SubagentFrame = {
      kind: "subagent_tool_call",
      task_id: "t1",
      subagent: "researcher",
      depth: 0,
      tool_name: "ls",
      tool_call_id: "c1",
    };
    const delegations = fold([start("t1"), call, call]);

    expect(named(delegations, "t1").steps).toHaveLength(1);
  });

  it("ignores a result for a call nothing announced", () => {
    // Two frames on one socket, and only one of them is guaranteed to have been
    // sent. A row invented from a result would have no name to show while it ran.
    const delegations = fold([
      start("t1"),
      {
        kind: "subagent_tool_result",
        task_id: "t1",
        subagent: "researcher",
        depth: 0,
        tool_name: "ls",
        tool_call_id: "unknown",
        ok: true,
      },
    ]);

    expect(named(delegations, "t1").steps).toEqual([]);
  });
});

describe("applyDelegationFrame - what a finished delegation reports", () => {
  it("closes the panel it names and writes what it cost", () => {
    const delegations = fold([
      start("t1"),
      finished("t1", { cost_usd: 0.0042, input_tokens: 1200, output_tokens: 340 }),
    ]);

    expect(named(delegations, "t1")).toMatchObject({
      status: "completed",
      costUsd: 0.0042,
      inputTokens: 1200,
      outputTokens: 340,
      error: null,
    });
  });

  it("carries the reason a delegation failed, so the panel is not simply empty", () => {
    const delegations = fold([
      start("t1"),
      finished("t1", { status: "failed", error: "the provider refused" }),
    ]);

    expect(named(delegations, "t1")).toMatchObject({
      status: "failed",
      error: "the provider refused",
    });
  });

  it("closes one delegation of a fan-out without touching the others", () => {
    const delegations = fold([start("t1"), start("t2"), finished("t1")]);

    expect(named(delegations, "t1").status).toBe("completed");
    expect(named(delegations, "t2").status).toBe("running");
  });

  it("drops a frame for a delegation nobody announced", () => {
    // The real case: a background delegation of the previous turn reporting after
    // the panels were replaced. A panel built from it would carry no delegate
    // name, no prompt, and no way to ever be closed.
    const before = fold([start("t1")]);
    const after = applyDelegationFrame(before, finished("t9"));

    expect(after).toBe(before);
  });
});

describe("applyDelegationFrame - nesting a specialist's own delegation", () => {
  it("hangs a deeper delegation off the open one above it", () => {
    const delegations = fold([
      start("t1", { subagent: "researcher", depth: 0 }),
      start("t2", { subagent: "assistant", depth: 1 }),
    ]);

    expect(named(delegations, "t2").parentTaskId).toBe("t1");
    expect(rootsOf(delegations).map((delegation) => delegation.taskId)).toEqual(["t1"]);
    expect(childrenOf(delegations, "t1").map((delegation) => delegation.taskId)).toEqual(["t2"]);
  });

  it("picks the specialist that is still working, not one that already answered", () => {
    const delegations = fold([
      start("t1", { subagent: "researcher", depth: 0 }),
      start("t2", { subagent: "writer", depth: 0 }),
      finished("t1"),
      start("t3", { subagent: "assistant", depth: 1 }),
    ]);

    expect(named(delegations, "t3").parentTaskId).toBe("t2");
  });

  it("shows a nested delegation whose parent cannot be found rather than hiding it", () => {
    // Only reachable if a start at depth 1 arrives with nothing open above it,
    // which is a library bug - and a panel at the top is a great deal better than
    // a delegation that streams into nothing anybody can see.
    const delegations = fold([start("t2", { depth: 1 })]);

    expect(named(delegations, "t2").parentTaskId).toBeNull();
    expect(rootsOf(delegations)).toHaveLength(1);
  });

  it("skips a candidate at the wrong depth when looking for a parent", () => {
    const delegations = fold([
      start("t1", { depth: 0 }),
      start("t2", { depth: 1 }),
      start("t3", { depth: 1 }),
    ]);

    // t3's parent is the depth-0 delegation, not the depth-1 sibling scanned first.
    expect(named(delegations, "t3").parentTaskId).toBe("t1");
  });
});

describe("closeOpenDelegations", () => {
  it("closes what was still running, because nothing more is coming", () => {
    const delegations = closeOpenDelegations(fold([start("t1"), start("t2"), finished("t2")]));

    expect(named(delegations, "t1").status).toBe("cancelled");
    // What already finished keeps the outcome it reported.
    expect(named(delegations, "t2").status).toBe("completed");
  });

  it("leaves a settled list exactly as it was", () => {
    // Identity, not equality: this runs on every `error` frame, including the ones
    // on turns that never delegated, and a new array there is a render for nothing.
    const settled = fold([start("t1"), finished("t1")]);

    expect(closeOpenDelegations(settled)).toBe(settled);
  });

  it("has nothing to do with no delegations at all", () => {
    const none: Delegation[] = [];

    expect(closeOpenDelegations(none)).toBe(none);
  });
});
