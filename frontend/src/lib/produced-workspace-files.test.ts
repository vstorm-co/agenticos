import { expect, it } from "vitest";
import type { ToolCall } from "@/types";
import {
  failedWorkspaceWrite,
  producedWorkspacePaths,
  workspaceLinkPath,
} from "./produced-workspace-files";
const write = (extra: Partial<ToolCall> = {}): ToolCall => ({
  id: "write",
  name: "write_file",
  status: "completed",
  args: { path: "files-panel-check.txt" },
  result: "Wrote 1 lines to /workspace/files-panel-check.txt",
  ...extra,
});
it("uses the real SDK write receipt and exact turn path, including renamed registry tools", () => {
  expect([...producedWorkspacePaths([write()])]).toEqual([
    ["files-panel-check.txt", "files-panel-check.txt"],
  ]);
  expect([
    ...producedWorkspacePaths([write({ name: "save", tool_id: "write_file" })]),
  ]).toHaveLength(1);
  expect([
    ...producedWorkspacePaths([
      write({
        name: "edit_file",
        result: "Edited /workspace/files-panel-check.txt: replaced 1 occurrence(s)",
      }),
    ]),
  ]).toHaveLength(1);
});
it.each([
  write({ status: "error" }),
  write({ status: "running" }),
  write({ status: "awaiting_approval" }),
  write({ name: "read_file" }),
  write({ presentation_kind: "generic" }),
  write({ presentation_kind: "generic", tool_id: "write_file", name: "mcp__remote__write_file" }),
  write({ presentation_kind: "platform", tool_id: "write_file" }),
  write({ presentation_kind: "draft", tool_id: "write_file" }),
  write({ name: "mcp__remote__write_file" }),
  write({ args: {} }),
  write({ result: "Error: permission denied" }),
  write({ result: { error: "failed" } }),
  write({ result: "written" }),
  write({ result: "Wrote 1 lines to /workspace/other.txt" }),
  write({ args: { path: "../files-panel-check.txt" } }),
])("does not invent link provenance from an unconfirmed or mismatched result %j", (call) => {
  expect(producedWorkspacePaths([call]).size).toBe(0);
});
it.each([
  "/workspace/../secret",
  "/workspace/%2e%2e/secret",
  "/workspace/%252e%252e/secret",
  "//host/workspace/a",
  "https://host/workspace/a",
  "/settings",
  "/Users/private/a",
  "a\\b",
  "a?x=1",
  "a#secret",
  "%broken",
  "a//b",
  "./a",
  "",
  "a\u0000b",
])("rejects ambiguous or non-workspace path %s", (path) => {
  expect(workspaceLinkPath(path)).toBeNull();
});
it("supports encoded spaces without matching unrelated basenames", () => {
  expect(workspaceLinkPath("/workspace/report%20one.txt")).toBe("report one.txt");
  expect(workspaceLinkPath("other/report.txt")).toBe("other/report.txt");
});
it("keeps legacy card success shapes but identifies explicit SDK and structured failures", () => {
  for (const result of ["Error: denied", " [Error: not found]", { error: "failed" }])
    expect(failedWorkspaceWrite(result)).toBe(true);
  for (const result of ["written", "edited", "ok", undefined, null, { error: null }])
    expect(failedWorkspaceWrite(result)).toBe(false);
});
