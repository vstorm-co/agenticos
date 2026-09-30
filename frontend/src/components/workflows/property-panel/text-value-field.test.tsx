import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEBUG_ECHO,
  echo,
  edge,
  graph,
  makeCatalog,
  makeDefinition,
  node,
  port,
} from "@/components/workflows/validation/fixtures";
import type { Binding, NodeOutputRef } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { BindingField } from "./binding-field";

/** A text parameter: typed text and values from earlier steps in one box. */

const FORM = makeDefinition({
  id: "test.form",
  name: "Form",
  ports: [
    port("out", "output", {
      type: "object",
      properties: { payload: { type: "object", additionalProperties: true } },
    }),
  ],
});
const catalog = makeCatalog([DEBUG_ECHO, FORM]);
const chain = graph({
  entry: "A",
  nodes: [node("A", "test.form"), echo("B")],
  edges: [edge("e", "A", "out", "B", "in")],
});

function ref(...path: string[]): NodeOutputRef {
  return { kind: "node_output", node_id: "A", port: "out", field_path: path };
}

function templated(...parts: (string | NodeOutputRef)[]): Binding {
  return { target_node_id: "B", target_field: "message", source: { kind: "template", parts } };
}

const literal = (value: string): Binding => ({
  target_node_id: "B",
  target_field: "message",
  source: { kind: "literal", value },
});

function mount(
  bindings: Binding[] = [],
  schema: Record<string, unknown> = { type: "string", title: "Message" },
  extra: { disabled?: boolean; required?: boolean; error?: string } = {},
) {
  const onUpsert = vi.fn();
  const onRemove = vi.fn();
  render(
    <BindingField
      targetNodeId="B"
      targetField="message"
      name="message"
      schema={schema}
      required={extra.required ?? false}
      bindings={bindings}
      graph={chain}
      catalog={catalog}
      error={extra.error}
      disabled={extra.disabled}
      onUpsert={onUpsert}
      onRemove={onRemove}
    />,
  );
  return { onUpsert, onRemove };
}

function carrying(field: unknown) {
  return {
    dataTransfer: {
      types: ["application/x-agenticos-step-field"],
      getData: () => (field === null ? "" : JSON.stringify(field)),
    },
  };
}

afterEach(() => useWorkflowEditorStore.getState().teardown());

describe("a text parameter", () => {
  it("stores typed text as it is, as it is typed, and nothing once emptied", () => {
    const { onUpsert, onRemove } = mount([literal("x")]);
    const box = screen.getByLabelText("Message");
    expect(box).toHaveValue("x");

    fireEvent.change(box, { target: { value: "Hello" } });
    expect(onUpsert).toHaveBeenLastCalledWith(literal("Hello"));
    fireEvent.change(box, { target: { value: "" } });
    expect(onRemove).toHaveBeenCalledWith("B", "message");
  });

  it("writes nothing for an empty box that held nothing", () => {
    const { onRemove } = mount();
    const box = screen.getByLabelText("Message");
    fireEvent.change(box, { target: { value: "a" } });
    fireEvent.change(box, { target: { value: "" } });
    // Nothing is saved for the field, so emptying the box has nothing to remove.
    expect(onRemove).not.toHaveBeenCalled();
  });

  it("turns text with a placeholder into a template, each placeholder a reference", () => {
    const { onUpsert } = mount([templated("x")]);
    const box = screen.getByLabelText("Message");
    expect(box).toHaveValue("x");

    fireEvent.change(box, { target: { value: "Hi {{Form.payload.name}}!" } });
    expect(onUpsert).toHaveBeenLastCalledWith(templated("Hi ", ref("payload", "name"), "!"));
  });

  it("says which placeholder names nothing it can read once left, and writes nothing", () => {
    const { onUpsert } = mount([templated("x")]);
    const box = screen.getByLabelText("Message");
    fireEvent.change(box, { target: { value: "Hi {{Nobody.name}}" } });
    expect(screen.queryByText(/names nothing this step can read/)).toBeNull();
    fireEvent.blur(box);
    expect(screen.getByText("{{Nobody.name}} names nothing this step can read.")).toBeTruthy();
    expect(onUpsert).not.toHaveBeenCalled();

    // Fixed, the message goes.
    fireEvent.change(box, { target: { value: "Hi" } });
    expect(screen.queryByText(/names nothing this step can read/)).toBeNull();
  });

  it("inserts a value picked from Data, or dropped from the Input pane, at the end", async () => {
    const { onUpsert } = mount([literal("Hi ")]);
    await userEvent.click(
      screen.getByRole("button", { name: "Insert data from an earlier step into Message" }),
    );
    expect(screen.getByText("Form")).toBeTruthy();
    await userEvent.click(screen.getByRole("menuitem", { name: /^payload/ }));
    expect(onUpsert).toHaveBeenLastCalledWith(templated("Hi ", ref("payload")));

    const box = screen.getByLabelText("Message");
    fireEvent.drop(box, carrying({ nodeId: "A", path: ["payload", "email"], type: "string" }));
    expect(onUpsert).toHaveBeenLastCalledWith(
      templated("Hi ", ref("payload"), ref("payload", "email")),
    );
  });

  it("inserts at the cursor while it is being typed in", () => {
    const { onUpsert } = mount([literal("Hi !")]);
    const box = screen.getByLabelText("Message") as HTMLInputElement;
    box.focus();
    box.setSelectionRange(3, 3);
    fireEvent.drop(box, carrying({ nodeId: "A", path: ["payload"], type: "object" }));
    expect(onUpsert).toHaveBeenLastCalledWith(templated("Hi ", ref("payload"), "!"));
  });

  it("refuses a dropped field it cannot read, and ignores anything else dropped", () => {
    const { onUpsert } = mount([literal("Hi ")]);
    const box = screen.getByLabelText("Message");
    fireEvent.drop(box, carrying({ nodeId: "B", path: ["echoed"], type: "string" }));
    expect(screen.getByText("{{Echo.echoed}} names nothing this step can read.")).toBeTruthy();
    fireEvent.drop(box, carrying(null));
    expect(onUpsert).not.toHaveBeenCalled();
  });

  it("shows what was written elsewhere, such as an undo", () => {
    const { rerender } = render(<Mounted bindings={[literal("one")]} />);
    expect(screen.getByLabelText("Message")).toHaveValue("one");
    rerender(<Mounted bindings={[literal("two")]} />);
    expect(screen.getByLabelText("Message")).toHaveValue("two");
  });

  it("previews the text with what the last test runs saw", () => {
    useWorkflowEditorStore
      .getState()
      .mergeStepData({ A: { output: { payload: { name: "Ada" } }, error: null, runId: "r" } });
    mount([templated("Hi ", ref("payload", "name"))]);
    expect(screen.getByText("Hi Ada")).toBeTruthy();
  });

  it("shows no preview before a run has anything for it", () => {
    mount([templated("Hi ", ref("payload", "name"))]);
    expect(screen.queryByText("Preview:")).toBeNull();
  });

  it("is several lines tall for a long text, says what it is for, and marks what is required", () => {
    mount(
      [],
      { type: "string", title: "Message", description: "What to say.", "x-multiline": true },
      { required: true, error: "Required." },
    );
    expect(screen.getByRole("textbox", { name: /^Message/ }).tagName).toBe("TEXTAREA");
    expect(screen.getByText("What to say.")).toBeTruthy();
    expect(screen.getByText("*")).toBeTruthy();
    expect(screen.getByText("Required.")).toBeTruthy();
  });

  it("offers no data to insert when it cannot be edited", () => {
    mount([literal("x")], undefined, { disabled: true });
    expect(screen.queryByRole("button", { name: /Insert data/ })).toBeNull();
    expect(screen.getByLabelText("Message")).toBeDisabled();
  });
});

function Mounted({ bindings }: { bindings: Binding[] }) {
  return (
    <BindingField
      targetNodeId="B"
      targetField="message"
      name="message"
      schema={{ type: "string", title: "Message" }}
      required={false}
      bindings={bindings}
      graph={chain}
      catalog={catalog}
      onUpsert={vi.fn()}
      onRemove={vi.fn()}
    />
  );
}
