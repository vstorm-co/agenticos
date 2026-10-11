import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StepName, StepNote, StepSwitch } from "./step-details";
import type { NodeInstance } from "@/lib/workflows/types";

const step: NodeInstance = {
  id: "n1",
  definition_id: "slack.message.send",
  definition_version: 1,
  config: {},
  layout: { x: 0, y: 0 },
};

function renderName(node: NodeInstance = step, disabled = false) {
  const onChange = vi.fn();
  render(
    <StepName
      node={node}
      name={node.label ?? "Send a message"}
      catalogName="Send a message"
      disabled={disabled}
      onChange={onChange}
    />,
  );
  return onChange;
}

describe("StepName", () => {
  it("renames the step where its name stands, trimmed, on Enter", async () => {
    const onChange = renderName();

    await userEvent.click(screen.getByRole("button", { name: "Send a message" }));
    const field = screen.getByRole("textbox", { name: "Step name" });
    expect(field).toHaveAttribute("placeholder", "Send a message");
    await userEvent.type(field, " Tell sales {Enter}");

    expect(onChange).toHaveBeenCalledWith("n1", { label: "Tell sales" });
    expect(screen.getByRole("button", { name: "Send a message" })).toBeInTheDocument();
  });

  it("falls back to the catalog's name when emptied, and writes nothing unchanged", async () => {
    const onChange = renderName({ ...step, label: "Tell sales" });

    await userEvent.click(screen.getByRole("button", { name: "Tell sales" }));
    await userEvent.clear(screen.getByRole("textbox", { name: "Step name" }));
    await userEvent.tab();
    expect(onChange).toHaveBeenCalledWith("n1", { label: null });

    onChange.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Tell sales" }));
    await userEvent.tab();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps the old name on Escape without closing what holds it", async () => {
    const onChange = renderName();
    const outer = vi.fn();
    document.addEventListener("keydown", outer);

    await userEvent.click(screen.getByRole("button", { name: "Send a message" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Step name" }), "x{Escape}");

    expect(onChange).not.toHaveBeenCalled();
    expect(outer).not.toHaveBeenCalledWith(expect.objectContaining({ key: "Escape" }));
    expect(screen.getByRole("button", { name: "Send a message" })).toBeInTheDocument();
    document.removeEventListener("keydown", outer);
  });

  it("is plain text on a step that cannot be edited", () => {
    renderName(step, true);
    expect(screen.getByText("Send a message")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("StepSwitch", () => {
  it("says whether the run carries the step out, and switches it off and on", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<StepSwitch node={step} onChange={onChange} />);

    const toggle = screen.getByRole("switch", { name: "Run this step" });
    expect(toggle).toBeChecked();
    await userEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith("n1", { disabled: true });

    rerender(<StepSwitch node={{ ...step, disabled: true }} onChange={onChange} />);
    await userEvent.click(screen.getByRole("switch", { name: "Run this step" }));
    expect(onChange).toHaveBeenLastCalledWith("n1", { disabled: false });
  });
});

describe("StepNote", () => {
  it("notes a step when the field is left, and clears an emptied note", () => {
    const onChange = vi.fn();
    const { rerender } = render(<StepNote node={step} disabled={false} onChange={onChange} />);

    fireEvent.blur(screen.getByLabelText("Note"));
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "For the EU team" } });
    fireEvent.blur(screen.getByLabelText("Note"));
    expect(onChange).toHaveBeenLastCalledWith("n1", { notes: "For the EU team" });

    rerender(
      <StepNote
        node={{ ...step, notes: "For the EU team" }}
        disabled={false}
        onChange={onChange}
      />,
    );
    expect(screen.getByLabelText("Note")).toHaveValue("For the EU team");
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: " " } });
    fireEvent.blur(screen.getByLabelText("Note"));
    expect(onChange).toHaveBeenLastCalledWith("n1", { notes: null });
  });

  it("shows nothing on a read-only step without a note, and the note on one with it", () => {
    const { unmount } = render(<StepNote node={step} disabled onChange={vi.fn()} />);
    expect(screen.queryByLabelText("Note")).toBeNull();
    unmount();
    render(<StepNote node={{ ...step, notes: "Kept" }} disabled onChange={vi.fn()} />);
    expect(screen.getByLabelText("Note")).toHaveValue("Kept");
  });
});
