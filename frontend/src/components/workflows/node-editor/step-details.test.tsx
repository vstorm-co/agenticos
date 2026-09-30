import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StepDetails } from "./step-details";
import type { NodeInstance } from "@/lib/workflows/types";

const step: NodeInstance = {
  id: "n1",
  definition_id: "slack.message.send",
  definition_version: 1,
  config: {},
  layout: { x: 0, y: 0 },
};

function renderDetails(overrides: Partial<Parameters<typeof StepDetails>[0]> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <StepDetails
      node={step}
      catalogName="Send a message"
      canSwitchOff
      disabled={false}
      onChange={onChange}
      {...overrides}
    />,
  );
  return { onChange, ...utils };
}

describe("StepDetails", () => {
  it("names a step and notes it when each field is left, and clears an emptied one", () => {
    const { onChange, rerender } = renderDetails();
    const name = screen.getByLabelText("Step name");
    expect(name).toHaveAttribute("placeholder", "Send a message");

    fireEvent.change(name, { target: { value: " Tell sales " } });
    fireEvent.blur(name);
    expect(onChange).toHaveBeenCalledWith("n1", { label: "Tell sales" });

    fireEvent.blur(name);
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "For the EU team" } });
    fireEvent.blur(screen.getByLabelText("Note"));
    expect(onChange).toHaveBeenLastCalledWith("n1", { notes: "For the EU team" });

    rerender(
      <StepDetails
        node={{ ...step, label: "Tell sales", notes: "For the EU team" }}
        catalogName="Send a message"
        canSwitchOff
        disabled={false}
        onChange={onChange}
      />,
    );
    expect(screen.getByLabelText("Step name")).toHaveValue("Tell sales");
    fireEvent.change(screen.getByLabelText("Step name"), { target: { value: "" } });
    fireEvent.blur(screen.getByLabelText("Step name"));
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: " " } });
    fireEvent.blur(screen.getByLabelText("Note"));
    expect(onChange.mock.calls.slice(-2)).toEqual([
      ["n1", { label: null }],
      ["n1", { notes: null }],
    ]);
  });

  it("writes nothing for a field left as it was", () => {
    const { onChange } = renderDetails();
    fireEvent.blur(screen.getByLabelText("Step name"));
    fireEvent.blur(screen.getByLabelText("Note"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("switches a step off, and offers no switch where there is nothing to skip", async () => {
    const { onChange, unmount } = renderDetails();
    await userEvent.click(screen.getByRole("switch", { name: "Switched off" }));
    expect(onChange).toHaveBeenCalledWith("n1", { disabled: true });
    unmount();

    renderDetails({ canSwitchOff: false });
    expect(screen.queryByRole("switch")).toBeNull();
  });
});
