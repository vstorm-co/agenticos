import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { InputField } from "@/lib/workflows/input-fields";

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

describe("StartRunDialog with declared fields", () => {
  const FIELDS: InputField[] = [
    {
      name: "email",
      label: "Email",
      type: "text",
      required: true,
      description: "Who to write to",
      options: [],
    },
    { name: "seats", label: null, type: "integer", required: true, description: null, options: [] },
    { name: "price", label: null, type: "number", required: false, description: null, options: [] },
    {
      name: "urgent",
      label: null,
      type: "boolean",
      required: true,
      description: "Page on-call",
      options: [],
    },
    { name: "due", label: "Due", type: "date", required: false, description: null, options: [] },
    {
      name: "plan",
      label: "Plan",
      type: "choice",
      required: true,
      description: null,
      options: ["basic", "pro"],
    },
  ];

  it("asks for each field by name and starts with the input typed as declared", async () => {
    const onStart = mount({ testFields: FIELDS });
    expect(screen.queryByLabelText("Input (JSON)")).toBeNull();
    expect(screen.getByText("Who to write to")).toBeTruthy();

    // Nothing filled in: every required field says so, and nothing starts.
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).not.toHaveBeenCalled();
    // Email, seats and the plan; the switch always has a value.
    expect(screen.getAllByText("Fill this in.")).toHaveLength(3);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ada@example.com" } });
    fireEvent.change(screen.getByLabelText("seats"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/price/), { target: { value: "9.5" } });
    fireEvent.change(screen.getByLabelText(/Due/), { target: { value: "2026-10-01" } });
    await userEvent.click(screen.getByRole("switch", { name: "urgent" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Plan" }));
    await userEvent.click(screen.getByRole("option", { name: "pro" }));
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));

    expect(onStart).toHaveBeenCalledWith({
      mode: "test",
      input: {
        email: "ada@example.com",
        seats: 3,
        price: 9.5,
        urgent: true,
        due: "2026-10-01",
        plan: "pro",
      },
    });
  });

  it("asks a real run for the published version's fields, not the draft's", async () => {
    const onStart = mount({ canTest: false, testFields: FIELDS, liveFields: [] });
    expect(screen.getByLabelText("Input (JSON)")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({ mode: "real", input: {} });
  });
});
