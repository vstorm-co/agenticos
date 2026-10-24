import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WorkflowDescription } from "./workflow-description";

describe("WorkflowDescription", () => {
  it("shows a reader the description as text", () => {
    render(<WorkflowDescription description="Scores leads" canEdit={false} onChange={vi.fn()} />);
    expect(screen.getByText("Scores leads")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("saves an edit on leaving the field, and clearing it removes the description", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<WorkflowDescription description="Scores leads" canEdit onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "Scores leads" }));
    const field = screen.getByRole("textbox", { name: "Workflow description" });
    await user.type(field, "{Enter}daily");
    await user.tab();
    expect(onChange).toHaveBeenLastCalledWith("Scores leads\ndaily");

    await user.click(screen.getByRole("button", { name: "Scores leads" }));
    await user.clear(screen.getByRole("textbox", { name: "Workflow description" }));
    await user.tab();
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("keeps the old text on Escape, and saves nothing unchanged", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<WorkflowDescription description={null} canEdit onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "Add a description" }));
    await user.type(screen.getByRole("textbox", { name: "Workflow description" }), "x{Escape}");
    expect(screen.getByRole("button", { name: "Add a description" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add a description" }));
    await user.type(screen.getByRole("textbox", { name: "Workflow description" }), "   ");
    await user.tab();
    expect(onChange).not.toHaveBeenCalled();
  });
});
