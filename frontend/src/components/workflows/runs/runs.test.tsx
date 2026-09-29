import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NodeRunStatusLabel, WorkflowRunStatusBadge } from "./run-status";
import { parseRunInput, StartRunDialog } from "./start-run-dialog";

describe("run status", () => {
  it("names a run's and a step's status in words", () => {
    render(
      <>
        <WorkflowRunStatusBadge status="waiting_approval" />
        <NodeRunStatusLabel status="skipped" />
      </>,
    );
    expect(screen.getByText("Waiting for approval")).toBeTruthy();
    expect(screen.getByText("Skipped")).toBeTruthy();
  });
});

describe("parseRunInput", () => {
  it("reads nothing as an empty input, and says what else is wrong", () => {
    expect(parseRunInput("  ")).toEqual({});
    expect(parseRunInput('{"a": 1}')).toEqual({ a: 1 });
    expect(parseRunInput("[1]")).toBe("notObject");
    expect(parseRunInput("{")).toBe("notJson");
  });
});

function mount(props: Partial<Parameters<typeof StartRunDialog>[0]> = {}) {
  const onStart = vi.fn();
  render(
    <StartRunDialog open onOpenChange={vi.fn()} canRunLive canTest onStart={onStart} {...props} />,
  );
  return onStart;
}

describe("StartRunDialog", () => {
  it("starts a test of the draft with the typed input", async () => {
    const onStart = mount();
    fireEvent.change(screen.getByLabelText("Input (JSON)"), { target: { value: '{"lead": 7}' } });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({ mode: "test", input: { lead: 7 } });
  });

  it("opens on the input the draft's trigger would hand on", async () => {
    const onStart = mount({ sampleInput: { body: {}, delivery_id: "test" } });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({
      mode: "test",
      input: { body: {}, delivery_id: "test" },
    });
  });

  it("starts the published version when that is all this caller may run", async () => {
    const onStart = mount({ canTest: false });
    fireEvent.change(screen.getByLabelText("Input (JSON)"), { target: { value: "" } });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({ mode: "real", input: {} });
  });

  it("switches between the draft and the published version", async () => {
    const onStart = mount();
    await userEvent.click(screen.getByRole("combobox", { name: "Run" }));
    await userEvent.click(screen.getByRole("option", { name: "Published version" }));
    fireEvent.change(screen.getByLabelText("Input (JSON)"), { target: { value: "{}" } });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({ mode: "real", input: {} });
  });

  it("refuses input that is not a JSON object, saying why", () => {
    const onStart = mount();
    fireEvent.change(screen.getByLabelText("Input (JSON)"), { target: { value: "[]" } });
    expect(screen.getByText("The input has to be a JSON object.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start a run" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).not.toHaveBeenCalled();
  });

  it("closes without starting anything", async () => {
    const onOpenChange = vi.fn();
    mount({ onOpenChange });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
