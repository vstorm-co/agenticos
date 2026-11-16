import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { InputField } from "@/lib/workflows/input-fields";
import { ApiError } from "@/lib/api-error";

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

  it("names a step switched off so, whatever its row says", () => {
    render(<NodeRunStatusLabel status="pending" switchedOff />);
    expect(screen.getByText("Switched off")).toBeTruthy();
    expect(screen.queryByText("Pending")).toBeNull();
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
  it("prefills the selected published entry rather than a different draft trigger", async () => {
    const onStart = mount({
      canTest: false,
      sampleInput: { body: { draft: true }, delivery_id: "draft" },
      liveEntries: [{ id: "live", name: "Published", fields: [], sample: { published: true } }],
    });
    expect(screen.getByLabelText("Input (JSON)")).toHaveValue(
      JSON.stringify({ published: true }, null, 2),
    );
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({
      mode: "real",
      input: { published: true },
      entry_node_id: "live",
    });
  });

  it("starts a published entry without a draft sample when no live sample is supplied", async () => {
    const onStart = mount({ canTest: false, sampleInput: { draftOnly: true } });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({ mode: "real", input: {} });
  });

  it("shows admission field paths beside JSON without echoing unrelated error data", () => {
    const onInputChange = vi.fn();
    mount({
      error: new ApiError(422, "Input rejected", {
        error: {
          code: "WORKFLOW_RUN_INPUT_INVALID",
          message: "Input rejected",
          details: {
            fields: [
              { field: "input.items.0.sku", message: "Field required" },
              { field: "nodes.start.config.input_schema", message: "Invalid trigger schema" },
            ],
            submitted: "private-request-value",
          },
        },
      }),
      onInputChange,
    });
    expect(screen.getByRole("alert")).toHaveTextContent("input.items.0.sku: Field required");
    expect(screen.queryByText("private-request-value")).not.toBeInTheDocument();
    expect(screen.queryByText("Invalid trigger schema")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Input (JSON)")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Input (JSON)")).toHaveAccessibleDescription(
      "input.items.0.sku: Field required",
    );
    fireEvent.change(screen.getByLabelText("Input (JSON)"), {
      target: { value: '{"items":[{"sku":"a"}]}' },
    });
    expect(onInputChange).toHaveBeenCalledOnce();
  });

  it("leaves graph configuration refusals outside the run input's errors", () => {
    mount({
      error: new ApiError(422, "Graph invalid", {
        error: {
          code: "GRAPH_INVALID",
          message: "Graph invalid",
          details: {
            fields: [
              {
                field: "nodes.start.config.input_schema",
                message: "Invalid trigger schema",
              },
            ],
          },
        },
      }),
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Input (JSON)")).toHaveAttribute("aria-invalid", "false");
  });

  it("clears admission errors when a version, entry or simple-field answer changes", async () => {
    const onInputChange = vi.fn();
    mount({
      onInputChange,
      entries: [
        { id: "one", name: "One", fields: [], sample: {} },
        { id: "two", name: "Two", fields: [], sample: {} },
      ],
      liveFields: [
        { name: "name", label: null, description: null, type: "text", required: true, options: [] },
      ],
    });
    await userEvent.click(screen.getByRole("combobox", { name: "Start from" }));
    await userEvent.click(screen.getByRole("option", { name: "Two" }));
    expect(onInputChange).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("combobox", { name: "Run" }));
    await userEvent.click(screen.getByRole("option", { name: "Published version" }));
    expect(onInputChange).toHaveBeenCalledTimes(2);
    fireEvent.change(screen.getByLabelText("name"), { target: { value: "Ada" } });
    expect(onInputChange).toHaveBeenCalledTimes(3);
  });

  it("keeps an admission request's input stable until it settles", async () => {
    const onOpenChange = vi.fn();
    const onInputChange = vi.fn();
    const props = {
      open: true,
      canRunLive: true,
      canTest: true,
      onStart: vi.fn(),
      onOpenChange,
      onInputChange,
    };
    const { rerender } = render(<StartRunDialog {...props} busy />);
    expect(screen.getByLabelText("Input (JSON)")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Run" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(onInputChange).not.toHaveBeenCalled();
    rerender(
      <StartRunDialog
        {...props}
        busy={false}
        error={
          new ApiError(422, "Input rejected", {
            error: {
              code: "WORKFLOW_RUN_INPUT_INVALID",
              message: "Input rejected",
              details: { fields: [{ field: "input.items", message: "Field required" }] },
            },
          })
        }
      />,
    );
    expect(screen.getByLabelText("Input (JSON)")).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "Run" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Input (JSON)"), { target: { value: '{"items":[]}' } });
    expect(onInputChange).toHaveBeenCalledOnce();
  });
  it("shows the contract of the selected version and preserves nested JSON input", async () => {
    const onStart = mount({
      testInputSchema: { type: "object", title: "Draft contact request" },
      liveInputSchema: { type: "object", title: "Published contact request" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Expected input schema" }));
    expect(screen.getByText("Draft contact request")).toBeVisible();
    await userEvent.click(screen.getByRole("combobox", { name: "Run" }));
    await userEvent.click(screen.getByRole("option", { name: "Published version" }));
    expect(screen.getByText("Published contact request")).toBeVisible();
    expect(screen.queryByText("Draft contact request")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Input (JSON)"), {
      target: { value: '{"contacts":[{"email":"ada@example.com","tags":["customer"]}]}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({
      mode: "real",
      input: { contacts: [{ email: "ada@example.com", tags: ["customer"] }] },
    });
  });

  it("shows only the selected entry's schema, leaving untyped entries open", async () => {
    mount({
      testInputSchema: { title: "Default fallback" },
      entries: [
        {
          id: "schema",
          name: "Schema start",
          fields: [],
          sample: {},
          inputSchema: { title: "Entry contract" },
        },
        { id: "open", name: "Open start", fields: [], sample: {} },
      ],
    });
    await userEvent.click(screen.getByRole("button", { name: "Expected input schema" }));
    expect(screen.getByText("Entry contract")).toBeVisible();
    expect(screen.queryByText("Default fallback")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Start from" }));
    await userEvent.click(screen.getByRole("option", { name: "Open start" }));
    expect(screen.queryByRole("button", { name: "Expected input schema" })).not.toBeInTheDocument();
  });

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
  it("requires a text list and submits its lines as an array", async () => {
    const onStart = mount({
      testFields: [
        {
          name: "devices",
          label: "Devices",
          type: "string_list",
          required: true,
          description: null,
          options: [],
        },
      ],
    });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).not.toHaveBeenCalled();
    const input = screen.getByRole("textbox", { name: "Devices" });
    expect(input.tagName).toBe("TEXTAREA");
    expect(input).toHaveAccessibleDescription("One item per line. Blank lines are ignored.");
    expect(input).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(input, { target: { value: "leaf-01\n\n leaf-02 " } });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(onStart).toHaveBeenCalledWith({
      mode: "test",
      input: { devices: ["leaf-01", "leaf-02"] },
    });
  });

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

it("lets an editor switch from an unavailable live contract to the draft", async () => {
  const onStart = vi.fn();
  const props = {
    open: true,
    onOpenChange: vi.fn(),
    canTest: true,
    canRunLive: true,
    sampleInput: { draft: true },
    onStart,
  };
  const { rerender } = render(<StartRunDialog {...props} />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Published version" }));
  rerender(
    <StartRunDialog {...props} canRunLive={false} liveNotice={<p>Live contract unavailable</p>} />,
  );
  expect(screen.getByRole("button", { name: "Start a run" })).toBeDisabled();
  await userEvent.click(screen.getByRole("combobox"));
  expect(screen.getByRole("option", { name: "Published version" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await userEvent.click(screen.getByRole("option", { name: "Test the draft" }));
  await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
  expect(onStart).toHaveBeenCalledWith({ mode: "test", input: { draft: true } });
});
