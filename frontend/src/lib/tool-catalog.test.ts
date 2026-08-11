import { describe, expect, it } from "vitest";

import { TOOL_CATALOG, isWorkspaceTool, toolEntry } from "./tool-catalog";

/**
 * The one table this side keys every tool decision on.
 *
 * The invariants here are what a *reader* of the table needs; whether it still
 * matches the backend is a question only the backend can answer, and
 * `backend/tests/test_capability_registry.py::TestFrontendToolCatalog` asks it. That
 * split is deliberate - the registry is the source of truth, and a test that reads a
 * hand-written copy of it proves nothing.
 */
describe("the tool catalog", () => {
  it("keys every row on a tool id the backend could actually emit", () => {
    // `TOOL_NAME_PATTERN` on the backend. A key with a hyphen or a capital is a key
    // no tool call will ever match, and nothing would say so.
    for (const id of Object.keys(TOOL_CATALOG)) {
      expect(id, id).toMatch(/^[a-z][a-z0-9_]*$/);
    }
  });

  it("gives a step something to say in both tenses", () => {
    // A row carries either a caption, for a step whose label is a sentence, or a verb
    // pair, for one whose label is a verb plus the file it is about. Neither leaves
    // the running step reading "Running Web Search", which is the fallback for a tool
    // this side has never heard of.
    for (const [id, entry] of Object.entries(TOOL_CATALOG)) {
      expect(entry.captionKey ?? entry.verbs, id).toBeDefined();
      expect(entry.captionKey !== undefined && entry.verbs !== undefined, id).toBe(false);
    }
  });

  it("opens only the calls whose whole value is what they produced", () => {
    const opens = Object.entries(TOOL_CATALOG)
      .filter(([, entry]) => entry.opensWhenDone === true)
      .map(([id]) => id);

    expect(opens.sort()).toEqual(["create_chart", "edit_file", "run_python", "write_file"]);
  });

  it("answers for a tool it has never heard of rather than throwing", () => {
    // The common path, not the exceptional one: an MCP server names its own tools,
    // and a binding may rename one this table lists.
    expect(toolEntry("linear_create_issue")).toBeNull();
    expect(isWorkspaceTool("linear_create_issue")).toBe(false);
  });

  it("renders the two tools that spent five weeks as raw JSON", () => {
    // #144: the backend renamed `web_search_tool` and `create_chart_tool` to the ids
    // below, the frontend went on matching the old names in three files, and both
    // calls fell through to the generic renderer - beside the renderers written for
    // them, with a wrench for an icon.
    expect(toolEntry("web_search")).toMatchObject({ kind: "web", render: "web-search" });
    expect(toolEntry("create_chart")).toMatchObject({ kind: "chart", render: "chart" });
  });
});
