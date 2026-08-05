import { describe, expect, it } from "vitest";

import {
  basename,
  contentArg,
  isWorkspaceTool,
  mcpCall,
  mcpToolPrefix,
  pathArg,
  stepKind,
  titleWords,
  toolStep,
} from "./tool-steps";

/**
 * The words a step is made of.
 *
 * Two properties carry the whole design. A step is written in the tense it is true in
 * - *Writing test1.md* while it runs and *Wrote test1.md* once it has - and the subject
 * is the file, the pattern or the command rather than the tool's function name, which
 * is the part nobody reads.
 */
describe("the line for one tool call", () => {
  it("writes a workspace call in the tense it is true in", () => {
    const args = { path: "/workspace/notes/test1.md", content: "hej" };

    expect(toolStep("write_file", args, false).label).toBe("Writing test1.md");
    expect(toolStep("write_file", args, true).label).toBe("Wrote test1.md");
  });

  it("names the file rather than its whole path", () => {
    // A step is a line in a narration, and `/workspace/skills/review/SKILL.md` is not
    // a line. The whole path is in the detail it opens.
    expect(toolStep("read_file", { path: "/workspace/skills/review/SKILL.md" }, true).label).toBe(
      "Read SKILL.md",
    );
  });

  it("keeps the whole path for a directory listing, which is what was listed", () => {
    expect(toolStep("ls", { path: "/workspace/out" }, true).label).toBe("Listed /workspace/out");
  });

  it("says what a search was looking for and where", () => {
    expect(toolStep("grep", { pattern: "TODO", path: "/src/app.py" }, true).label).toBe(
      "Searched for TODO in app.py",
    );
    expect(toolStep("glob", { pattern: "**/*.py" }, false).label).toBe("Looking for **/*.py");
  });

  it("says which command ran", () => {
    expect(toolStep("execute", { command: "pytest -q" }, true).label).toBe("Ran pytest -q");
  });

  it("still reads as a sentence when the arguments carried no subject", () => {
    // A malformed call, or one whose arguments have not streamed in yet.
    expect(toolStep("write_file", {}, false).label).toBe("Writing…");
    expect(toolStep("write_file", undefined, true).label).toBe("Wrote…");
  });

  it("keeps the captions the other tools had", () => {
    expect(toolStep("search_documents", {}, false).label).toBe("Searching the documents");
    expect(toolStep("search_documents", {}, true).label).toBe("Knowledge Base Search");
  });

  it("says what happened rather than naming the tool, where the two differ", () => {
    expect(toolStep("fetch_url", { url: "https://a.example/" }, true).label).toBe("Fetched page");
    // Which skill it was is the whole content of the step.
    expect(toolStep("load_skill", { skill_name: "refund_policy" }, true).label).toBe(
      "Refund Policy",
    );
    expect(toolStep("load_skill", {}, true).label).toBe("Load Skill");
  });

  it("carries the query or the URL as the detail beside a finished call", () => {
    expect(toolStep("search_web", { query: "refund law" }, true).detail).toBe("refund law");
    expect(toolStep("post_invoice", { invoice_id: 7 }, true).detail).toBeNull();
  });

  it("picks the icon from what the call is about", () => {
    expect(stepKind("write_file")).toBe("write");
    expect(stepKind("grep")).toBe("search");
    expect(stepKind("execute")).toBe("shell");
    expect(stepKind("post_invoice")).toBe("tool");
  });
});

/**
 * Naming a call that came from an MCP server.
 *
 * Nothing on a tool call says where it came from: the only trace is the prefix the
 * backend puts on every tool of a connection, which is the connection's name. So the
 * rule here mirrors `app/agents/mcp.py::_tool_prefix`, and drift costs a step reading
 * "Github Work Create Issue" - which is what a miss already looks like.
 */
describe("a call from an MCP server", () => {
  it("mirrors the backend's prefix rule", () => {
    expect(mcpToolPrefix("github-work")).toBe("github_work");
    expect(mcpToolPrefix("Linear")).toBe("linear");
    expect(mcpToolPrefix("!!!")).toBe("mcp");
  });

  it("names the server and what was asked of it", () => {
    const step = toolStep("linear_create_issue", {}, true, [
      { name: "Linear", url: "https://mcp.linear.app/sse" },
    ]);

    expect(step.label).toBe("Linear · Create issue");
    expect(step.kind).toBe("mcp");
    expect(step.logoDomain).toBe("mcp.linear.app");
  });

  it("prefers the longest prefix, because connection names nest", () => {
    // "github" and "github_work" both match `github_work_create_issue`, and only the
    // longer one is right.
    const match = mcpCall("github_work_create_issue", [
      { name: "github", url: "https://a.example/" },
      { name: "github-work", url: "https://b.example/" },
    ]);

    expect(match?.server).toBe("github-work");
    expect(match?.action).toBe("create_issue");
  });

  it("claims nothing when no server owns the prefix", () => {
    expect(mcpCall("write_file", [{ name: "Linear", url: "https://a.example/" }])).toBeNull();
    // The prefix alone is not a call: a tool named exactly after its connection has
    // nothing left to be the action.
    expect(mcpCall("linear_", [{ name: "Linear", url: "https://a.example/" }])).toBeNull();
  });

  it("has no logo to show for a URL it cannot parse", () => {
    expect(
      mcpCall("linear_create_issue", [{ name: "Linear", url: "not a url" }])?.domain,
    ).toBeNull();
  });

  it("leaves the workspace tools alone even when a connection shares their name", () => {
    // A connection called "Execute" would otherwise swallow the shell tool.
    const step = toolStep("execute", { command: "ls" }, true, [
      { name: "ls", url: "https://a.example/" },
    ]);

    expect(step.label).toBe("Ran ls");
  });
});

describe("reading a call's arguments", () => {
  it("finds the path under any of the names a tool uses for it", () => {
    expect(pathArg({ path: "/a" })).toBe("/a");
    expect(pathArg({ file_path: "/b" })).toBe("/b");
    expect(pathArg({ filename: "/c" })).toBe("/c");
    expect(pathArg({})).toBeNull();
  });

  it("finds the body of a write or an edit", () => {
    expect(contentArg({ content: "a" })).toBe("a");
    expect(contentArg({ new_string: "b" })).toBe("b");
    expect(contentArg({ path: "/a" })).toBeNull();
  });

  it("takes the name off a path, and title-cases words", () => {
    expect(basename("/a/b/c.md")).toBe("c.md");
    expect(basename("plain.md")).toBe("plain.md");
    expect(titleWords("market_data")).toBe("Market Data");
  });

  it("claims only the tools that come from the backends library", () => {
    expect(isWorkspaceTool("edit_file")).toBe(true);
    expect(isWorkspaceTool("create_chart_tool")).toBe(false);
  });

  it("has no subject for a search with no pattern, and reads a command under either name", () => {
    // A call whose arguments have not streamed in yet, and the shell tool's two
    // spellings of the same thing.
    expect(toolStep("grep", {}, true).label).toBe("Searched for…");
    expect(toolStep("execute", { cmd: "ls -la" }, true).label).toBe("Ran ls -la");
  });

  it("names a skill only when the call said which", () => {
    expect(toolStep("load_skill", { skill_name: "  " }, true).label).toBe("Load Skill");
  });

  it("reads a path under any name a tool gives it, and a query when there is none", () => {
    expect(toolStep("read_file", { file_path: "/a/b.txt" }, true).label).toBe("Read b.txt");
    expect(toolStep("read_file", { filename: "c.txt" }, true).label).toBe("Read c.txt");
    expect(toolStep("post_invoice", { url: "https://a.example/" }, true).detail).toBe(
      "https://a.example/",
    );
    expect(toolStep("load_skill", { skill_name: "refunds" }, false).detail).toBe("refunds");
  });

  it("finds a write's body under any of the names a tool uses", () => {
    expect(contentArg({ text: "a" })).toBe("a");
    expect(contentArg({ new_str: "b" })).toBe("b");
    expect(contentArg(undefined)).toBeNull();
    expect(pathArg(undefined)).toBeNull();
  });
});
