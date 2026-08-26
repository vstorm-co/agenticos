import { describe, expect, it } from "vitest";

import { parsePlan, planProgress, progressOf } from "./plan-state";
import type { ChatMessage, ToolCall } from "@/types";

/**
 * The plan, read back out of the calls the agent made to keep it.
 *
 * Nothing streams a plan frame, so the surfaces that draw one fold the planning
 * tool results in order. That fold is the part worth pinning: a granular call
 * knows one step's worth of the plan, so reading the last call alone shows a
 * checklist of one, and treating a refusal (`Plan not updated: …`) as a plan
 * erases the plan that is still in place.
 */

function call(overrides: Partial<ToolCall>): ToolCall {
  return { id: "tc", name: "write_plan", args: {}, status: "completed", ...overrides };
}

function turn(...calls: ToolCall[]): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "",
    timestamp: new Date(0),
    toolCalls: calls,
  };
}

const WRITTEN = [
  "Plan updated: 3 step(s).",
  "",
  "1. [x] Read the diff",
  "2. [~] Write the test",
  "3. [ ] Push it",
  "(1/3 completed)",
].join("\n");

describe("parsing a rendered plan", () => {
  it("reads a step's status off its glyph", () => {
    expect(parsePlan(WRITTEN)).toEqual([
      { id: null, content: "Read the diff", status: "completed" },
      { id: null, content: "Write the test", status: "in_progress" },
      { id: null, content: "Push it", status: "pending" },
    ]);
  });

  it("reads the ids the detailed rendering carries", () => {
    // `read_plan` renders `1. [ ] [a1b2c3d4] content`, and the ids are what the
    // batch update names its steps by.
    expect(parsePlan("Current plan:\n1. [!] [a1b2c3d4] Wait for the migration")).toEqual([
      { id: "a1b2c3d4", content: "Wait for the migration", status: "blocked" },
    ]);
  });

  it("answers null for text that carries no checklist", () => {
    // Not an empty plan: `No plan yet.` and a refused write both mean the plan is
    // whatever it already was, and a fold that emptied it would erase one on a typo.
    expect(parsePlan("No plan yet.")).toBeNull();
    expect(parsePlan("Plan not updated: Duplicate step ids: a1.")).toBeNull();
  });

  it("skips a numbered line whose glyph means nothing here", () => {
    expect(parsePlan("1. [?] Something else entirely")).toBeNull();
  });
});

describe("the plan a conversation now stands at", () => {
  it("is null until something plans", () => {
    expect(planProgress([turn(call({ name: "read_file", result: "x" }))])).toBeNull();
    expect(planProgress([])).toBeNull();
  });

  it("ignores every call that is not a planning one", () => {
    const plan = planProgress([
      turn(call({ result: WRITTEN }), call({ name: "write_file", result: "wrote it" })),
    ]);

    expect(plan?.total).toBe(3);
  });

  it("counts what is done, what is running, and how far along it is", () => {
    const plan = planProgress([turn(call({ result: WRITTEN }))]);

    expect(plan).toMatchObject({ completed: 1, total: 3, percent: 33, finished: false });
    expect(plan?.active?.content).toBe("Write the test");
  });

  it("follows a single status change made three calls later", () => {
    // The reason the fold exists: `update_task_status` answers with one sentence
    // about one step, so the last call knows a third of this plan.
    const plan = planProgress([
      turn(
        call({ result: WRITTEN }),
        call({
          name: "update_task_status",
          result: "Updated step 'Write the test' status to 'completed'.",
        }),
      ),
    ]);

    expect(plan?.completed).toBe(2);
    expect(plan?.active).toBeNull();
  });

  it("follows a batch update, by id or by content", () => {
    const plan = planProgress([
      turn(
        call({ result: "Current plan:\n1. [ ] [aa11] Read the diff\n2. [ ] Push it" }),
        call({
          name: "update_task_statuses",
          result:
            "Updated 2 step(s):\n- [aa11] Read the diff -> completed\n- [bb22] Push it -> in_progress",
        }),
      ),
    ]);

    expect(plan?.steps.map((step) => step.status)).toEqual(["completed", "in_progress"]);
  });

  it("appends a step added on its own", () => {
    const plan = planProgress([
      turn(
        call({ result: WRITTEN }),
        call({ name: "add_task", result: "Added step 'Tell the user' with id: cc33" }),
      ),
    ]);

    expect(plan?.total).toBe(4);
    expect(plan?.steps.at(-1)).toEqual({ id: "cc33", content: "Tell the user", status: "pending" });
  });

  it("keeps the plan a refused write did not change", () => {
    const plan = planProgress([
      turn(
        call({ result: WRITTEN }),
        call({ result: "Plan not updated: Duplicate step ids: aa11." }),
      ),
    ]);

    expect(plan?.total).toBe(3);
  });

  it("shows the plan a call is still writing, from its arguments", () => {
    // What makes the strip appear as the agent plans rather than a turn later.
    const plan = planProgress([
      turn(
        call({
          status: "running",
          result: undefined,
          args: {
            items: [
              { content: "Read the diff", status: "in_progress" },
              { content: "Push it" },
              { nonsense: true },
            ],
          },
        }),
      ),
    ]);

    expect(plan?.steps).toEqual([
      { id: null, content: "Read the diff", status: "in_progress" },
      { id: null, content: "Push it", status: "pending" },
    ]);
  });

  it("reads a replayed turn's calls off its parts, and counts each call once", () => {
    const message: ChatMessage = {
      ...turn(call({ result: WRITTEN })),
      parts: [{ id: "p1", type: "tool", toolCall: call({ result: WRITTEN }) }],
    };

    expect(planProgress([message])?.total).toBe(3);
  });

  it("ignores a status neither the tools nor this side know", () => {
    // A single line and a batch line, both naming something that is not a status.
    const written = call({ result: "1. [ ] [aa11] Read the diff" });
    const single = planProgress([
      turn(
        written,
        call({
          name: "update_task_status",
          result: "Updated step 'Read the diff' status to 'sideways'.",
        }),
      ),
    ]);
    const batch = planProgress([
      turn(
        written,
        call({ name: "update_task_statuses", result: "- [aa11] Read the diff -> sideways" }),
      ),
    ]);

    expect(single?.steps[0]?.status).toBe("pending");
    expect(batch?.steps[0]?.status).toBe("pending");
  });

  it("leaves the plan alone for a granular call still in flight", () => {
    // Only `write_plan` carries the plan in its arguments; the rest carry an id.
    const plan = planProgress([
      turn(
        call({ result: WRITTEN }),
        call({ name: "update_task_status", status: "running", result: undefined }),
      ),
    ]);

    expect(plan?.completed).toBe(1);
  });

  it("keeps the plan when a call in flight is not writing one after all", () => {
    // `write_plan` with no `items` yet - the frame arrived before the arguments
    // finished streaming - and one whose items say nothing this side can use.
    const nothingYet = planProgress([
      turn(call({ result: WRITTEN }), call({ status: "running", result: undefined, args: {} })),
    ]);
    const nothingUseful = planProgress([
      turn(
        call({ result: WRITTEN }),
        call({ status: "running", result: undefined, args: { items: [{ nonsense: 1 }] } }),
      ),
    ]);

    expect(nothingYet?.total).toBe(3);
    expect(nothingUseful?.total).toBe(3);
  });

  it("keeps the ids a plan was written with", () => {
    const plan = planProgress([
      turn(
        call({
          status: "running",
          result: undefined,
          args: { items: [{ id: "zz99", content: "X" }] },
        }),
      ),
    ]);

    expect(plan?.steps[0]?.id).toBe("zz99");
  });

  it("reads a result that arrived as an object rather than as text", () => {
    // Nothing plans in JSON, but the socket hands back whatever shape it was given,
    // and a plan is not what came back.
    expect(planProgress([turn(call({ result: { unexpected: true } }))])).toBeNull();
  });

  it("reads a turn that has parts but no tool call in them", () => {
    const message: ChatMessage = {
      ...turn(call({ result: WRITTEN })),
      parts: [{ id: "p1", type: "text", content: "planning" }],
    };

    expect(planProgress([message])?.total).toBe(3);
  });

  it("reads a turn carrying neither parts nor calls", () => {
    const message: ChatMessage = {
      id: "m",
      role: "assistant",
      content: "",
      timestamp: new Date(0),
    };

    expect(planProgress([message])).toBeNull();
  });

  it("calls a plan finished when every step is settled one way or another", () => {
    const plan = planProgress([
      turn(call({ result: "1. [x] Read the diff\n2. [-] Push it\n(1/2 completed)" })),
    ]);

    expect(plan?.finished).toBe(true);
    expect(plan?.percent).toBe(50);
  });
});

describe("what a checklist adds up to", () => {
  it("has nothing to divide by for an empty one", () => {
    expect(progressOf([])).toMatchObject({ percent: 0, finished: false, active: null });
  });
});
