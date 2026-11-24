import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { PlatformMcpServerRef } from "@/types/agents";
import type { PlatformMcpTool } from "@/types/mcp";
import { PlatformToolChecklist, withToolApproval } from "./platform-tool-checklist";

const TOOLS: PlatformMcpTool[] = [
  { name: "run_agent", description: "Run an agent.", group: "agents", writes: true },
  {
    name: "add_virtual_table_record",
    description: "Add one record.",
    group: "tables",
    writes: true,
  },
  {
    name: "query_virtual_table",
    description: "Query records.",
    group: "tables",
    writes: false,
  },
  { name: "list_agents", description: "The agents.", group: "agents", writes: false },
];

const BINDING: PlatformMcpServerRef = {
  account: "platform",
  allowed_tools: null,
  approval: "writes",
};

function Harness({
  initial = BINDING,
  tools = TOOLS,
  onChange,
}: {
  initial?: PlatformMcpServerRef;
  tools?: PlatformMcpTool[];
  onChange: (next: PlatformMcpServerRef) => void;
}) {
  const [binding, setBinding] = useState(initial);
  return (
    <TooltipProvider>
      <PlatformToolChecklist
        tools={tools}
        binding={binding}
        onChange={(next) => {
          setBinding(next);
          onChange(next);
        }}
      />
    </TooltipProvider>
  );
}

/** The section a group heading opens. */
function group(name: string): HTMLElement {
  return screen.getByRole("heading", { name }).closest("section")!;
}

describe("the platform's tools, grouped by what they work on", () => {
  it("shows the groups in their order, reads before changes, each change marked", () => {
    render(<Harness onChange={vi.fn()} />);

    expect(screen.getAllByRole("heading").map((heading) => heading.textContent)).toEqual([
      "Tables",
      "Agents",
    ]);
    const tables = within(group("Tables")).getAllByRole("checkbox", {
      name: /virtual_table/,
    });
    expect(tables.map((box) => box.getAttribute("aria-label"))).toEqual([
      "query_virtual_table",
      "add_virtual_table_record",
    ]);
    const marks = within(group("Tables")).getAllByRole("img", { name: "Changes something" });
    expect(marks).toHaveLength(1);
  });

  it("lets one change run freely, and dropping it back leaves nothing of its own", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const name = "Ask first before add_virtual_table_record";
    const shield = screen.getByRole("button", { name });
    expect(shield).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(shield);
    expect(onChange).toHaveBeenLastCalledWith({
      ...BINDING,
      tool_approval: { add_virtual_table_record: "never" },
    });
    expect(within(group("Tables")).getByRole("combobox")).toHaveTextContent("Run freely");

    await userEvent.click(shield);
    expect(onChange).toHaveBeenLastCalledWith(BINDING);
  });

  it("sets every tool of a group, reads included, and leaves the binding's default", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.click(within(group("Agents")).getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Ask first" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...BINDING,
      tool_approval: { list_agents: "required" },
    });

    await userEvent.click(within(group("Agents")).getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Run freely" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...BINDING,
      tool_approval: { run_agent: "never" },
    });
  });

  it("reports mixed table approvals including mandatory confirmation and preserves that floor", async () => {
    const onChange = vi.fn();
    const tables: PlatformMcpTool[] = [
      {
        name: "list_tables",
        description: "List tables.",
        group: "tables",
        writes: false,
        default_approval_free: true,
      },
      {
        name: "add_record",
        description: "Add a record.",
        group: "tables",
        writes: true,
        default_approval_free: true,
      },
      {
        name: "delete_table",
        description: "Delete a table.",
        group: "tables",
        writes: true,
        always_asks: true,
      },
    ];
    render(<Harness tools={tables} onChange={onChange} />);
    const choice = within(group("Tables")).getByRole("combobox");
    const deletion = screen.getByRole("button", { name: "Ask first before delete_table" });
    expect(choice).toHaveTextContent("Per tool");
    expect(choice).toBeEnabled();
    await userEvent.click(choice);
    await userEvent.click(screen.getByRole("option", { name: "Ask first" }));
    expect(choice).toHaveTextContent("Ask first");
    await userEvent.click(choice);
    await userEvent.click(screen.getByRole("option", { name: "Run freely" }));
    expect(choice).toHaveTextContent("Per tool");
    expect(deletion).toBeDisabled();
    expect(deletion).toHaveAttribute("aria-pressed", "true");
    for (const name of ["list_tables", "add_record"]) {
      expect(screen.getByRole("button", { name: `Ask first before ${name}` })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    }
    expect(onChange).toHaveBeenLastCalledWith(
      expect.not.objectContaining({
        tool_approval: expect.objectContaining({ delete_table: "never" }),
      }),
    );
  });

  it("shows an all-mandatory administration group as Ask first with only approval selection disabled", async () => {
    const onChange = vi.fn();
    render(
      <Harness
        tools={[
          {
            name: "update_deployment",
            description: "Update settings.",
            group: "administration",
            writes: true,
            always_asks: true,
          },
          {
            name: "delete_org",
            description: "Delete a workspace.",
            group: "administration",
            writes: true,
            always_asks: true,
          },
        ]}
        onChange={onChange}
      />,
    );
    const section = within(group("Administration"));
    expect(section.getByRole("combobox")).toHaveTextContent("Ask first");
    expect(section.getByRole("combobox")).toBeDisabled();
    const enable = section.getByRole("checkbox", { name: "Every tool in Administration" });
    expect(enable).toBeEnabled();
    await userEvent.click(enable);
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ allowed_tools: [] }));
  });

  it("leaves the tools whose approval is fixed out of their group's choice", async () => {
    const onChange = vi.fn();
    const account: PlatformMcpTool[] = [
      { name: "whoami", description: "Who is asking.", group: "account", writes: false },
      {
        name: "set_my_language",
        description: "Switch the language.",
        group: "account",
        writes: true,
        ungated: true,
      },
      {
        name: "invite_member",
        description: "Invite a member.",
        group: "account",
        writes: true,
        always_asks: true,
      },
    ];
    render(
      <Harness
        tools={account}
        initial={{ ...BINDING, tool_approval: { invite_member: "never" } }}
        onChange={onChange}
      />,
    );
    const choice = () => within(group("Organization and account")).getByRole("combobox");
    const invite = screen.getByRole("button", { name: "Ask first before invite_member" });
    expect(invite).toBeDisabled();
    expect(invite).toHaveAttribute("aria-pressed", "true");
    expect(invite).toHaveAttribute("title", "always asks for confirmation");

    // Every read asking is the default `all`, so a read added later asks too; the
    // `never` nobody may set on inviting is not carried forward.
    await userEvent.click(choice());
    await userEvent.click(screen.getByRole("option", { name: "Ask first" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...BINDING, approval: "all" });
    // The language tool still never asks, even when all editable tools ask.
    expect(choice()).toHaveTextContent("Per tool");
  });

  it("goes back to `writes` once one read runs freely again", async () => {
    const onChange = vi.fn();
    render(<Harness initial={{ ...BINDING, approval: "all" }} onChange={onChange} />);

    const shield = screen.getByRole("button", { name: "Ask first before list_agents" });
    await userEvent.click(shield);

    expect(onChange).toHaveBeenLastCalledWith({
      ...BINDING,
      tool_approval: { query_virtual_table: "required" },
    });
  });

  it("drops a tool's own approval when the tool is no longer chosen", async () => {
    const onChange = vi.fn();
    const initial = { ...BINDING, tool_approval: { run_agent: "never" as const } };
    render(<Harness initial={initial} onChange={onChange} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "run_agent" }));

    expect(onChange).toHaveBeenLastCalledWith({
      ...BINDING,
      allowed_tools: ["add_virtual_table_record", "query_virtual_table", "list_agents"],
    });
  });

  it("reads a binding saved as `none` the way the server does - changes ask", () => {
    render(<Harness initial={{ ...BINDING, approval: "none" }} onChange={vi.fn()} />);

    const shield = screen.getByRole("button", { name: "Ask first before run_agent" });
    expect(shield).toHaveAttribute("aria-pressed", "true");
    expect(within(group("Tables")).getByRole("combobox")).toHaveTextContent("Per tool");
  });

  it("narrows to the tools a search names or describes, and drops a group with none", async () => {
    render(<Harness onChange={vi.fn()} />);
    const shown = () =>
      screen.getAllByRole("checkbox", { name: /_/ }).map((box) => box.getAttribute("aria-label"));

    // In a description only: "Query records." - no tool's name says "records".
    await userEvent.type(screen.getByRole("textbox", { name: "Search tools" }), "records");

    expect(screen.getAllByRole("heading").map((heading) => heading.textContent)).toEqual([
      "Tables",
    ]);
    expect(shown()).toEqual(["query_virtual_table"]);
  });

  it("narrows by ticking, and every tool chosen again is today's tools only", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "Every tool in Tables" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...BINDING,
      allowed_tools: ["run_agent", "list_agents"],
    });
    expect(screen.getByRole("switch", { name: "Add tools the server gains later" })).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: "Every tool in Tables" }));
    const today = TOOLS.map((tool) => tool.name);
    expect(onChange).toHaveBeenLastCalledWith({ ...BINDING, allowed_tools: today });

    await userEvent.click(screen.getByRole("switch", { name: "Add tools the server gains later" }));
    expect(onChange).toHaveBeenLastCalledWith(BINDING);
  });
});

describe("withToolApproval", () => {
  it("writes the tools' own approvals sorted, and none at all as no key", () => {
    expect(withToolApproval(BINDING, { b: "never", a: "required" })).toEqual({
      ...BINDING,
      tool_approval: { a: "required", b: "never" },
    });
    expect(withToolApproval({ ...BINDING, tool_approval: { a: "never" } }, {})).toEqual(BINDING);
  });
});

it("shows a default-free write truthfully and still lets the author require approval", async () => {
  const onChange = vi.fn();
  const tools: PlatformMcpTool[] = [
    {
      name: "create_task",
      description: "Create a task.",
      group: "tasks",
      writes: true,
      default_approval_free: true,
    },
    { name: "list_tasks", description: "Read tasks.", group: "tasks", writes: false },
  ];
  render(<Harness tools={tools} onChange={onChange} />);
  const row = screen.getByText("Create task").closest("li");
  if (!row) throw new Error("missing create task row");
  const shield = within(row).getByRole("button", { name: "Ask first before create_task" });
  expect(shield).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(shield);
  expect(onChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ tool_approval: { create_task: "required" } }),
  );
  expect(within(row).getByRole("button", { name: "Ask first before create_task" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("keeps default-free writes gated under a binding that asks for every call", () => {
  render(
    <Harness
      initial={{ ...BINDING, approval: "all" }}
      tools={[
        {
          name: "create_task",
          description: "Create a task.",
          group: "tasks",
          writes: true,
          default_approval_free: true,
        },
      ]}
      onChange={vi.fn()}
    />,
  );
  const row = screen.getByText("Create task").closest("li");
  if (!row) throw new Error("missing create task row");
  expect(within(row).getByRole("button", { name: "Ask first before create_task" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("explains conditional task execution while keeping author approval configurable", () => {
  render(
    <Harness
      onChange={vi.fn()}
      tools={[
        {
          name: "create_task",
          description: "Create task",
          group: "agents",
          writes: true,
          default_approval_free: true,
          conditional_approval: true,
        },
      ]}
    />,
  );
  expect(screen.getByText(/may start or reschedule agent work/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Ask first before create_task" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});
