import { describe, expect, it } from "vitest";

import { callSummary, quotedPrice, serviceAction, spokenArgs } from "./approval-view";

describe("serviceAction", () => {
  it("reads an MCP tool as its service and the action, without the service twice", () => {
    expect(serviceAction("notion_notion-search", false)).toEqual({
      service: "notion",
      action: "Search",
    });
    expect(serviceAction("linear_create_issue", false)).toEqual({
      service: "linear",
      action: "Create issue",
    });
  });

  it("reads a prefix as a service only where something says it is one", () => {
    expect(serviceAction("send_email", false)).toEqual({ service: null, action: "send_email" });
    expect(serviceAction("acme_do-thing", false)).toEqual({ service: "acme", action: "Do thing" });
  });

  it("leaves a built-in tool, a name with no prefix and a bare prefix as they are", () => {
    expect(serviceAction("write_memory", true)).toEqual({ service: null, action: "write_memory" });
    expect(serviceAction("execute", false)).toEqual({ service: null, action: "execute" });
    expect(serviceAction("notion_notion", false)).toEqual({
      service: null,
      action: "notion_notion",
    });
  });
});

describe("callSummary", () => {
  it("summarizes structured CRM searches instead of exposing serialized requests", () => {
    const request = { filterGroups: [{ filters: [{ propertyName: "name", value: "Oasis*" }] }] };
    expect(callSummary({ query: JSON.stringify(request) })).toBe("Oasis*");
    expect(callSummary(request)).toBe("Oasis*");
    expect(callSummary({ request: JSON.stringify(request) })).toBe("Oasis*");
  });

  it("preserves bracketed subjects and shell conditions as readable text", () => {
    for (const query of [
      "[Action required] Contract",
      "[Q4]",
      "[2026] Annual report",
      "{Draft} Contract",
      "[ -f README.md ] && cat README.md",
      '[ "$READY" = yes ] && deploy',
      "{ curl https://example.com; }",
      '{ printf "%s" ok; }',
    ]) {
      expect(callSummary({ query })).toBe(query);
    }
  });

  it("does not decode or hide a literal command even when it resembles JSON or an ID", () => {
    for (const command of ["[]", '{"query":"delete"}', "ed7b79b6-02bf-4303-a08c-9b95e37af56f"]) {
      expect(callSummary({ command }, { omitOpaqueIds: true })).toBe(command);
    }
    expect(callSummary({ cmd: "[]" })).toBe("[]");
  });

  it("leaves opaque IDs and uninterpretable serialized requests to the details", () => {
    const target = "ed7b79b6-02bf-4303-a08c-9b95e37af56f";
    expect(callSummary({ record_id: target }, { omitOpaqueIds: true })).toBeNull();
    expect(callSummary({ record_id: target })).toBe(target);
    for (const query of ["[]", '{"token":"private"}', "{".repeat(8193)]) {
      expect(callSummary({ query })).toBeNull();
    }
    expect(callSummary({ payload: { payload: { query: '{"query":"too deep"}' } } })).toBeNull();
  });

  it("keeps a bounded, distinct set of meaningful search terms", () => {
    expect(
      callSummary({
        filterGroups: [
          null,
          {},
          {
            filters: [
              null,
              {},
              { value: 4 },
              { value: "" },
              { value: "A" },
              { value: "A" },
              { value: "B" },
              { value: "C" },
              { value: "D" },
            ],
          },
        ],
      }),
    ).toBe("A · B · C");
    expect(callSummary({ filterGroups: [{}] })).toBeNull();
    expect(callSummary({ query: "", title: "Readable title" })).toBe("Readable title");
  });

  it("picks the argument that says what the call is about", () => {
    expect(callSummary({ page_url: "", query: "what's new", sort: "relevance" })).toBe(
      "what's new",
    );
    expect(callSummary({ command: "ls -la\nrm -rf /tmp/x" })).toBe("ls -la");
  });

  it("falls back to the first words there are, and to nothing", () => {
    expect(callSummary({ kind: "index", other: 3 })).toBe("index");
    expect(callSummary({ size: 10, flag: true })).toBeNull();
    expect(callSummary({})).toBeNull();
  });

  it("stops a long line short", () => {
    const summary = callSummary({ query: "x".repeat(400) })!;
    expect(summary).toHaveLength(160);
    expect(summary.endsWith("…")).toBe(true);
  });
});

describe("spokenArgs", () => {
  it("drops every field that says nothing, at every depth", () => {
    expect(
      spokenArgs({
        query: "q",
        page_url: "",
        teamspace_ids: [],
        nothing: null,
        size: 0,
        flag: false,
        filters: {
          created: { start: "2026-01-01", end: "" },
          ids: ["", ""],
          empty: {},
        },
        tags: ["a", ""],
      }),
    ).toEqual({
      query: "q",
      size: 0,
      flag: false,
      filters: { created: { start: "2026-01-01" } },
      tags: ["a", ""],
    });
  });
});

it("names a platform operation and its nested task before opaque IDs", () => {
  expect(serviceAction("agenticos_create_task", false)).toEqual({
    service: "AgenticOS",
    action: "Create task",
  });
  expect(
    callSummary({
      table_id: "table-uuid",
      task: { title: "Review supplier draft", notes: "Details" },
    }),
  ).toBe("Review supplier draft");
  expect(callSummary({ payload: { data: { title: "Prepare the report" } } })).toBe(
    "Prepare the report",
  );
});

describe("quotedPrice", () => {
  it("reads the price a paid platform call carries", () => {
    expect(quotedPrice("agenticos_start_eval_run", { quoted_usd: "0.40" })).toBe("0.40");
    expect(quotedPrice("agenticos_improve_again", { estimate_usd: 0.2 })).toBe("0.2");
    expect(quotedPrice("agenticos_run_next_improvement_step", { total_usd: "1.5" })).toBe("1.5");
  });

  it("reads nothing from another tool or an argument that is not an amount", () => {
    expect(quotedPrice("send_email", { quoted_usd: "0.40" })).toBeNull();
    expect(quotedPrice("agenticos_start_eval_run", { quoted_usd: "soon" })).toBeNull();
    expect(quotedPrice("agenticos_publish_agent", {})).toBeNull();
  });
});
