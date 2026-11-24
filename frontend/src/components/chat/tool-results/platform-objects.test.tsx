import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ToolCall } from "@/types";
import { platformObjects, PlatformObjects, platformCallError } from "./platform-objects";

const id = "10000000-0000-4000-8000-000000000001";
const tableId = "20000000-0000-4000-8000-000000000002";
function call(name: string, value: unknown, status: ToolCall["status"] = "completed"): ToolCall {
  return { id: name, name, args: {}, status, result: JSON.stringify(value) };
}
describe("platform objects", () => {
  it("links a successful task to its real table with its title and status", () => {
    render(
      <PlatformObjects
        calls={[
          call("agenticos_create_task", {
            id,
            table_id: tableId,
            title: "Review the draft",
            status: "waiting_for_user",
          }),
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: /Review the draft/ })).toHaveAttribute(
      "href",
      `/tables/${tableId}`,
    );
    expect(screen.getByText("Waiting for you")).toBeInTheDocument();
  });
  it("never turns an error, pending operation or unrelated payload into a created object", () => {
    expect(
      platformObjects([
        call("agenticos_create_task", { id, table_id: tableId, error: { message: "Refused" } }),
        call("agenticos_create_project", { id, name: "Pending" }, "running"),
        call("read_skill_resource", { id, name: "Not a project" }),
        call("agenticos_create_project", { id: "https://example.com", name: "Bad id" }),
      ]),
    ).toEqual([]);
  });
  it("keeps one card per record and resolves its title from the actual table schema", () => {
    const result = platformObjects([
      call("agenticos_get_virtual_table", {
        id: tableId,
        columns: [{ id: "title", label: "Task", type: "text" }],
      }),
      call("agenticos_add_virtual_table_record", {
        id,
        table_id: tableId,
        values: { title: "First title" },
      }),
      call("agenticos_update_virtual_table_record", {
        id,
        table_id: tableId,
        values: { title: "Updated title" },
      }),
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]?.title).toBe("Updated title");
  });
});

it.each([
  ["agenticos_create_project", "Project", `/projects/${id}`],
  ["agenticos_create_virtual_table", "Table", `/tables/${id}`],
  ["agenticos_create_agent_draft", "Agent", `/agents/${id}`],
  ["agenticos_create_workflow_draft", "Workflow", `/workflows/${id}`],
  ["agenticos_create_skill", "Skill", "/skills"],
  ["agenticos_create_context_file", "Context file", "/context"],
])("opens the saved object for %s", (name, label, href) => {
  render(<PlatformObjects calls={[call(name, { id, name: "Saved resource" })]} />);
  expect(screen.getByRole("link", { name: new RegExp(label) })).toHaveAttribute("href", href);
  expect(screen.getByText("Saved resource")).toBeInTheDocument();
});

it("recognizes a platform refusal even when the transport completed", () => {
  expect(
    platformCallError(
      call("agenticos_create_task", { error: { message: "Project does not match" } }),
    ),
  ).toBe("Project does not match");
  expect(platformCallError(call("agenticos_create_task", { id, title: "Saved" }))).toBeNull();
  expect(
    platformCallError(call("other_tool", { error: { message: "Not a platform envelope" } })),
  ).toBeNull();
});

it("ignores malformed provider JSON instead of presenting it as a platform object", () => {
  expect(
    platformObjects([{ ...call("agenticos_create_project", null), result: "{invalid" }]),
  ).toEqual([]);
});

it("does not hide an unexpected parser failure as an empty object list", () => {
  const parse = vi.spyOn(JSON, "parse").mockImplementationOnce(() => {
    throw new Error("Parser failed");
  });
  try {
    expect(() => platformObjects([call("agenticos_create_project", { id })])).toThrow(
      "Parser failed",
    );
  } finally {
    parse.mockRestore();
  }
});

it("shows current platform results only with server-owned provenance", () => {
  const created = call("agenticos_create_project", { id, name: "Plan" });
  expect(platformObjects([{ ...created, presentation_kind: "platform" }])).toHaveLength(1);
  expect(platformObjects([{ ...created, presentation_kind: "generic" }])).toEqual([]);
  expect(platformObjects([{ ...created, tool_id: "create_chart" }])).toEqual([]);
  const refusal = call("agenticos_create_project", { error: { message: "Refused" } });
  expect(platformCallError({ ...refusal, presentation_kind: "platform" })).toBe("Refused");
  expect(platformCallError({ ...refusal, presentation_kind: "generic" })).toBeNull();
});
