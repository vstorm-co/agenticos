import { describe, expect, it } from "vitest";

import { callSummary, serviceAction, spokenArgs } from "./approval-view";

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
