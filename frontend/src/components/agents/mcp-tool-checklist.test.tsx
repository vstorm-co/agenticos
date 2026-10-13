import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { McpToolChecklist } from "./mcp-tool-checklist";

const MANY = Array.from({ length: 10 }, (_, i) => ({
  name: `tool_${i}`,
  description: i === 3 ? "Opens an invoice" : `Does thing ${i}`,
}));

describe("McpToolChecklist", () => {
  it("searches a long list by name or description", async () => {
    render(<McpToolChecklist tools={MANY} allowed={null} onChange={vi.fn()} />);

    await userEvent.type(screen.getByRole("textbox", { name: "Search tools" }), "invoice");

    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(screen.getByRole("checkbox", { name: "tool_3" })).toBeInTheDocument();
  });

  it("offers no search over a short list", () => {
    render(<McpToolChecklist tools={MANY.slice(0, 3)} allowed={null} onChange={vi.fn()} />);

    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("clears every tool at once, and ticks one back", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <McpToolChecklist tools={MANY.slice(0, 3)} allowed={null} onChange={onChange} />,
    );

    await userEvent.click(screen.getByRole("checkbox", { name: "tool_0" }));
    expect(onChange).toHaveBeenLastCalledWith(["tool_1", "tool_2"]);
    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onChange).toHaveBeenLastCalledWith([]);

    rerender(<McpToolChecklist tools={MANY.slice(0, 3)} allowed={[]} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "tool_1" }));
    expect(onChange).toHaveBeenLastCalledWith(["tool_1"]);
  });
});
