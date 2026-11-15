import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { McpToolInfo } from "@/lib/mcp-connections-api";
import type { McpApproval, McpToolApproval } from "@/types/agents";
import { asksFirst, McpToolChecklist, readableToolName } from "./mcp-tool-checklist";

const MANY: McpToolInfo[] = Array.from({ length: 10 }, (_, i) => ({
  name: `tool_${i}`,
  description: i === 3 ? "Opens an invoice" : `Does thing ${i}`,
}));

const NOTION: McpToolInfo[] = [
  { name: "notion-search", description: "Search the workspace", read_only: true },
  { name: "notion-fetch", description: "Read a page", read_only: true },
  { name: "notion-create-pages", description: "Create pages" },
];

function checklist(
  props: Partial<{
    tools: McpToolInfo[];
    allowed: string[] | null;
    onChange: (next: string[] | null) => void;
    approval: McpApproval;
    toolApproval: McpToolApproval;
    onApproval: (next: McpApproval, toolApproval: McpToolApproval) => void;
  }> = {},
) {
  return (
    <McpToolChecklist
      tools={props.tools ?? NOTION}
      allowed={props.allowed ?? null}
      onChange={props.onChange ?? vi.fn()}
      approval={props.approval ?? "writes"}
      toolApproval={props.toolApproval ?? {}}
      onApproval={props.onApproval ?? vi.fn()}
      prefix="notion"
    />
  );
}

/** A tool's own approval control, pressed while it asks first. */
const own = (name: string) => screen.getByRole("button", { name: `Ask first before ${name}` });

const group = (name: string) => screen.getByRole("heading", { name }).closest("section")!;

describe("readableToolName", () => {
  it("drops the server's prefix and spells the rest as words", () => {
    expect(readableToolName("notion-create-pages", "notion")).toBe("Create pages");
    expect(readableToolName("Notion_search", "notion")).toBe("Search");
    expect(readableToolName("list_recent_files", null)).toBe("List recent files");
    expect(readableToolName("notionsearch", "notion")).toBe("Notionsearch");
  });
});

describe("McpToolChecklist", () => {
  it("groups the reads apart from the tools that change things, by readable names", () => {
    render(checklist());

    expect(within(group("Reads")).getByText("Search")).toBeInTheDocument();
    expect(within(group("Reads")).getByText("2 of 2")).toBeInTheDocument();
    expect(within(group("Changes things")).getByText("Create pages")).toBeInTheDocument();
    // The server's own name and description are a hover away.
    expect(screen.getByText("Search").closest("label")).toHaveAttribute(
      "title",
      "notion-search - Search the workspace",
    );
  });

  it("is one group of tools where the server marks nothing read-only", () => {
    render(checklist({ tools: MANY.slice(0, 3) }));

    expect(screen.queryByRole("heading", { name: "Reads" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Tools" })).toBeInTheDocument();
  });

  it("draws no empty group, and names a tool with no description by its own name", () => {
    render(checklist({ tools: [{ name: "notion-get-self", description: "", read_only: true }] }));

    expect(screen.queryByRole("heading", { name: "Changes things" })).toBeNull();
    expect(screen.getByText("Get self").closest("label")).toHaveAttribute(
      "title",
      "notion-get-self",
    );
  });

  it("searches a long list by name or description", async () => {
    render(checklist({ tools: MANY }));

    await userEvent.type(screen.getByRole("textbox", { name: "Search tools" }), "invoice");

    expect(screen.getByRole("checkbox", { name: "tool_3" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "tool_4" })).toBeNull();
  });

  it("offers no search over a short list", () => {
    render(checklist());

    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("narrows one tool, a whole group, and back to every tool", async () => {
    const onChange = vi.fn();
    const { rerender } = render(checklist({ onChange }));

    await userEvent.click(screen.getByRole("checkbox", { name: "notion-fetch" }));
    expect(onChange).toHaveBeenLastCalledWith(["notion-search", "notion-create-pages"]);

    await userEvent.click(screen.getByRole("checkbox", { name: "Every tool in Reads" }));
    expect(onChange).toHaveBeenLastCalledWith(["notion-create-pages"]);

    rerender(checklist({ onChange, allowed: ["notion-create-pages"] }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Every tool in Reads" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("says the approval per group, as the binding's one setting", async () => {
    const onApproval = vi.fn();
    const { rerender } = render(checklist({ onApproval }));

    expect(screen.getByRole("combobox", { name: "Approval for Reads" })).toHaveTextContent(
      "Run freely",
    );
    expect(screen.getByRole("combobox", { name: "Approval for Changes things" })).toHaveTextContent(
      "Ask first",
    );

    // Asking before a read is asking before everything.
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Reads" }));
    await userEvent.click(await screen.findByRole("option", { name: "Ask first" }));
    expect(onApproval).toHaveBeenLastCalledWith("all", {});

    // Letting changes run lets everything run.
    rerender(checklist({ onApproval, approval: "all" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Changes things" }));
    await userEvent.click(await screen.findByRole("option", { name: "Run freely" }));
    expect(onApproval).toHaveBeenLastCalledWith("none", {});

    rerender(checklist({ onApproval, approval: "none" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Changes things" }));
    await userEvent.click(await screen.findByRole("option", { name: "Ask first" }));
    expect(onApproval).toHaveBeenLastCalledWith("writes", {});

    rerender(checklist({ onApproval, approval: "all" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Reads" }));
    await userEvent.click(await screen.findByRole("option", { name: "Run freely" }));
    expect(onApproval).toHaveBeenLastCalledWith("writes", {});
  });

  it("lets a server's reads run while its writes ask, where it marks nothing read-only", async () => {
    // The case per-tool approval exists for (#2884): one group, every tool in it a
    // write as far as the server says, and `writes` asking before all of them.
    const onApproval = vi.fn();
    const unmarked = MANY.slice(0, 3);
    const { rerender } = render(checklist({ tools: unmarked, onApproval }));

    expect(own("tool_0")).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(own("tool_0"));
    expect(onApproval).toHaveBeenLastCalledWith("writes", { tool_0: "never" });

    rerender(checklist({ tools: unmarked, onApproval, toolApproval: { tool_0: "never" } }));
    expect(own("tool_0")).toHaveAttribute("aria-pressed", "false");
    expect(own("tool_1")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("combobox", { name: "Approval for Tools" })).toHaveTextContent(
      "Per tool",
    );
  });

  it("asks before one tool whatever its group does, and follows the group once set back", async () => {
    const onApproval = vi.fn();
    const { rerender } = render(checklist({ approval: "none", onApproval }));

    await userEvent.click(own("notion-fetch"));
    expect(onApproval).toHaveBeenLastCalledWith("none", { "notion-fetch": "required" });

    rerender(
      checklist({ approval: "none", onApproval, toolApproval: { "notion-fetch": "required" } }),
    );
    await userEvent.click(own("notion-fetch"));
    expect(onApproval).toHaveBeenLastCalledWith("none", {});
  });

  it("sets every tool of a group that differs, and leaves the other group's own", async () => {
    const onApproval = vi.fn();
    render(
      checklist({
        onApproval,
        toolApproval: { "notion-search": "required", "notion-create-pages": "never" },
      }),
    );

    expect(screen.getByRole("combobox", { name: "Approval for Reads" })).toHaveTextContent(
      "Per tool",
    );
    // Every tool in Changes things runs freely, so that group still has one answer.
    expect(screen.getByRole("combobox", { name: "Approval for Changes things" })).toHaveTextContent(
      "Run freely",
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Reads" }));
    await userEvent.click(await screen.findByRole("option", { name: "Run freely" }));

    expect(onApproval).toHaveBeenLastCalledWith("writes", { "notion-create-pages": "never" });
  });

  it("sets a group whose tools differ to one answer, whatever the policy", async () => {
    // Only a group that reads "Per tool" can be set to what its policy already
    // says, and the choice then clears the group's tools of their own.
    const onApproval = vi.fn();
    const { rerender } = render(
      checklist({ approval: "none", toolApproval: { "notion-search": "required" }, onApproval }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Reads" }));
    await userEvent.click(await screen.findByRole("option", { name: "Run freely" }));
    expect(onApproval).toHaveBeenLastCalledWith("none", {});

    const writes = [...NOTION, { name: "notion-delete-page", description: "Delete" }];
    rerender(
      checklist({
        tools: writes,
        approval: "all",
        toolApproval: { "notion-delete-page": "never" },
        onApproval,
      }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Changes things" }));
    await userEvent.click(await screen.findByRole("option", { name: "Ask first" }));
    expect(onApproval).toHaveBeenLastCalledWith("all", {});
  });

  it("asks nothing of a viewer who cannot edit", () => {
    render(
      <McpToolChecklist
        tools={NOTION}
        allowed={null}
        onChange={vi.fn()}
        approval="writes"
        toolApproval={{}}
        onApproval={vi.fn()}
        prefix="notion"
        disabled
      />,
    );

    expect(own("notion-search")).toBeDisabled();
  });
});

describe("asksFirst", () => {
  const write = { name: "delete", description: "" };
  const read = { name: "search", description: "", read_only: true };

  it.each(["constructor", "toString", "__proto__"])(
    "ignores inherited properties when the tool is named %s",
    (name) => {
      const tool = { name, description: "" };
      expect(asksFirst(tool, "writes", {})).toBe(true);
      expect(asksFirst(tool, "all", {})).toBe(true);
      expect(asksFirst(tool, "none", {})).toBe(false);
      expect(asksFirst(tool, "writes", { [name]: "never" })).toBe(false);
      expect(asksFirst(tool, "none", { [name]: "required" })).toBe(true);
    },
  );

  it("lets a tool's own approval win over the policy and the server's hint", () => {
    expect(asksFirst(write, "writes", { delete: "never" })).toBe(false);
    expect(asksFirst(read, "none", { search: "required" })).toBe(true);
    expect(asksFirst(read, "all", { search: "never" })).toBe(false);
  });

  it("otherwise asks as the policy says, trusting only the read-only hint", () => {
    expect(asksFirst(write, "writes", {})).toBe(true);
    expect(asksFirst(read, "writes", {})).toBe(false);
    expect(asksFirst(read, "all", {})).toBe(true);
    expect(asksFirst(write, "none", {})).toBe(false);
  });
});
