import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { McpToolInfo } from "@/lib/mcp-connections-api";
import type { McpApproval } from "@/types/agents";
import { McpToolChecklist, readableToolName } from "./mcp-tool-checklist";

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
    onApproval: (next: McpApproval) => void;
  }> = {},
) {
  return (
    <McpToolChecklist
      tools={props.tools ?? NOTION}
      allowed={props.allowed ?? null}
      onChange={props.onChange ?? vi.fn()}
      approval={props.approval ?? "writes"}
      onApproval={props.onApproval ?? vi.fn()}
      prefix="notion"
    />
  );
}

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
    expect(onApproval).toHaveBeenLastCalledWith("all");

    // Letting changes run lets everything run.
    rerender(checklist({ onApproval, approval: "all" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Changes things" }));
    await userEvent.click(await screen.findByRole("option", { name: "Run freely" }));
    expect(onApproval).toHaveBeenLastCalledWith("none");

    rerender(checklist({ onApproval, approval: "none" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Changes things" }));
    await userEvent.click(await screen.findByRole("option", { name: "Ask first" }));
    expect(onApproval).toHaveBeenLastCalledWith("writes");

    rerender(checklist({ onApproval, approval: "all" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Reads" }));
    await userEvent.click(await screen.findByRole("option", { name: "Run freely" }));
    expect(onApproval).toHaveBeenLastCalledWith("writes");
  });
});
