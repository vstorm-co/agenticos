import { describe, expect, it } from "vitest";

import {
  PROPOSE_SETUP,
  REQUEST_CAPABILITY,
  SUGGEST_NEXT_STEPS,
  capabilityCardsOf,
  drawnUnderTheAnswer,
  followUpsOf,
  memoryChangesOf,
  setupProposalsOf,
} from "./turn-extras";
import type { ToolCall } from "@/types/chat";

/**
 * What a turn's calls leave under its answer, read off the calls themselves -
 * so the streamed turn and the reloaded one draw the same thing.
 */

function call(name: string, overrides: Partial<ToolCall> = {}): ToolCall {
  return { id: `${name}-1`, name, args: {}, status: "completed", ...overrides };
}

describe("drawnUnderTheAnswer", () => {
  it("takes the next steps out of the run's steps, and leaves a real tool in them", () => {
    expect(drawnUnderTheAnswer(SUGGEST_NEXT_STEPS)).toBe(true);
    expect(drawnUnderTheAnswer(REQUEST_CAPABILITY)).toBe(true);
    expect(drawnUnderTheAnswer(PROPOSE_SETUP)).toBe(true);
    expect(drawnUnderTheAnswer("web_search")).toBe(false);
    expect(drawnUnderTheAnswer("an_mcp_tool")).toBe(false);
  });
});

describe("followUpsOf", () => {
  it("offers the last suggestion's steps, as the server kept them", () => {
    const calls = [
      call(SUGGEST_NEXT_STEPS, { id: "s-1", result: JSON.stringify({ steps: ["old"] }) }),
      call(SUGGEST_NEXT_STEPS, {
        id: "s-2",
        result: JSON.stringify({ steps: ["Draft it", "", 3] }),
      }),
    ];

    expect(followUpsOf(calls)).toEqual(["Draft it"]);
  });

  it("offers nothing for a call still running, a result that is not the shape, or none at all", () => {
    expect(followUpsOf(undefined)).toEqual([]);
    expect(followUpsOf([call(SUGGEST_NEXT_STEPS, { status: "running" })])).toEqual([]);
    expect(followUpsOf([call(SUGGEST_NEXT_STEPS, { result: "not json" })])).toEqual([]);
    expect(followUpsOf([call(SUGGEST_NEXT_STEPS, { result: "[1]" })])).toEqual([]);
    expect(followUpsOf([call(SUGGEST_NEXT_STEPS, { result: { steps: ["a"] } })])).toEqual([]);
    expect(followUpsOf([call(SUGGEST_NEXT_STEPS, { result: '{"steps": "a"}' })])).toEqual([]);
  });
});

describe("capabilityCardsOf", () => {
  const card = { agent_id: "a-1", capability_id: "web_search", name: "Web search", reason: "news" };

  it("draws one card per capability the turn asked for", () => {
    const calls = [call(REQUEST_CAPABILITY, { id: "r-1", result: JSON.stringify(card) })];

    expect(capabilityCardsOf(calls)).toEqual([
      {
        callId: "r-1",
        agentId: "a-1",
        capabilityId: "web_search",
        name: "Web search",
        reason: "news",
      },
    ]);
  });

  it("draws no card from a result missing a field", () => {
    const { reason: _reason, ...partial } = card;

    expect(
      capabilityCardsOf([call(REQUEST_CAPABILITY, { result: JSON.stringify(partial) })]),
    ).toEqual([]);
    expect(capabilityCardsOf([call(REQUEST_CAPABILITY, { result: "refused" })])).toEqual([]);
    expect(capabilityCardsOf(undefined)).toEqual([]);
  });
});

describe("memoryChangesOf", () => {
  it("names a saved note by what the agent called it, else by its file", () => {
    const calls = [
      call("write_memory", {
        id: "w-1",
        args: { name: "role.md", description: "Your role is sales" },
      }),
      call("edit_memory", { id: "e-1", args: { name: "team.md", description: "" } }),
    ];

    expect(memoryChangesOf(calls)).toEqual([
      { callId: "w-1", forgot: false, label: "Your role is sales" },
      { callId: "e-1", forgot: false, label: "team.md" },
    ]);
  });

  it("says what was forgotten", () => {
    expect(memoryChangesOf([call("delete_memory", { args: { name: "role.md" } })])).toEqual([
      { callId: "delete_memory-1", forgot: true, label: "role.md" },
    ]);
  });

  it("leaves out the agent's own index, a failed save, another tool and a nameless note", () => {
    expect(
      memoryChangesOf([
        call("write_memory", { args: { name: "MEMORY.md" } }),
        call("write_memory", { status: "error", args: { name: "a.md" } }),
        call("read_memory", { args: { name: "a.md" } }),
        call("write_memory", { args: {} }),
      ]),
    ).toEqual([]);
    expect(memoryChangesOf(undefined)).toEqual([]);
  });
});

describe("setupProposalsOf", () => {
  const routine = {
    kind: "routine",
    title: "Monday digest",
    why: "You read tickets every Monday",
    request: "Summarise last week's tickets",
    cron: "0 7 * * 1",
  };

  it("draws the last proposal's cards, each keyed on its call", () => {
    const calls = [
      call(PROPOSE_SETUP, { id: "p-1", result: JSON.stringify({ proposals: [routine] }) }),
      call(PROPOSE_SETUP, {
        id: "p-2",
        result: JSON.stringify({
          proposals: [
            routine,
            {
              ...routine,
              kind: "connection",
              request: "Gmail",
              cron: null,
              server: "com.mintmcp/gmail",
            },
          ],
        }),
      }),
    ];

    expect(setupProposalsOf(calls)).toEqual([
      { key: "p-2-0", ...routine, server: null },
      {
        key: "p-2-1",
        ...routine,
        kind: "connection",
        request: "Gmail",
        cron: null,
        server: "com.mintmcp/gmail",
      },
    ]);
  });

  it("leaves out a card the console cannot draw", () => {
    const result = JSON.stringify({
      proposals: [
        null,
        "a routine",
        { ...routine, kind: "webinar" },
        { ...routine, title: 3 },
        { ...routine, why: undefined },
        { ...routine, request: ["x"] },
        { ...routine, kind: "agent", cron: 7, server: "" },
      ],
    });

    expect(setupProposalsOf([call(PROPOSE_SETUP, { id: "p", result })])).toEqual([
      { key: "p-6", ...routine, kind: "agent", cron: null, server: null },
    ]);
  });

  it("draws nothing for a call still running, a result of another shape, or none at all", () => {
    expect(setupProposalsOf(undefined)).toEqual([]);
    expect(setupProposalsOf([call(PROPOSE_SETUP, { status: "running" })])).toEqual([]);
    expect(setupProposalsOf([call(PROPOSE_SETUP, { result: "not json" })])).toEqual([]);
    expect(setupProposalsOf([call(PROPOSE_SETUP, { result: '{"proposals": {}}' })])).toEqual([]);
  });
});
