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

/** A text field's Template mode: text with values from earlier steps in it. */

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

function mount(
  bindings: Binding[] = [],
  schema: Record<string, unknown> = { type: "string", title: "Message" },
) {
  const onUpsert = vi.fn();
  const onRemove = vi.fn();
  render(
    <BindingField
      targetNodeId="B"
      targetField="message"
      name="message"
      schema={schema}
      required={false}
      bindings={bindings}
      graph={chain}
      catalog={catalog}
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

describe("a template field", () => {
  it("is offered for text only, and switching to it clears what was there", async () => {
    const literal: Binding = {
      target_node_id: "B",
      target_field: "message",
      source: { kind: "literal", value: "hi" },
    };
    const { onRemove } = mount([literal]);
    await userEvent.click(screen.getByRole("radio", { name: "Template" }));
    expect(onRemove).toHaveBeenCalledWith("B", "message");
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("is not offered for a field that does not take text", () => {
    mount([], { type: "integer", title: "Count" });
    expect(screen.queryByRole("radio", { name: "Template" })).toBeNull();
  });

  it("writes the text it is given, each placeholder as a reference", () => {
    const { onUpsert, onRemove } = mount([templated("x")]);
    const box = screen.getByLabelText("Message");
    expect(box).toHaveValue("x");

    fireEvent.change(box, { target: { value: "Hi {{Form.payload.name}}!" } });
    fireEvent.blur(box);
    expect(onUpsert).toHaveBeenCalledWith(templated("Hi ", ref("payload", "name"), "!"));

    fireEvent.change(box, { target: { value: "" } });
    fireEvent.blur(box);
    expect(onRemove).toHaveBeenCalledWith("B", "message");
  });

  it("says which placeholder names nothing it can read, and writes nothing", () => {
    const { onUpsert } = mount([templated("x")]);
    const box = screen.getByLabelText("Message");
    fireEvent.change(box, { target: { value: "Hi {{Nobody.name}}" } });
    fireEvent.blur(box);
    expect(screen.getByText("{{Nobody.name}} names nothing this step can read.")).toBeTruthy();
    expect(onUpsert).not.toHaveBeenCalled();
  });

  it("inserts a value picked from the list, or dropped from the Input pane, at the end", async () => {
    const { onUpsert } = mount([templated("Hi ")]);
    await userEvent.click(screen.getByRole("combobox", { name: "Insert a value into Message" }));
    await userEvent.click(screen.getByRole("option", { name: "{{Form.payload}}" }));
    expect(onUpsert).toHaveBeenLastCalledWith(templated("Hi ", ref("payload")));

    const box = screen.getByLabelText("Message");
    fireEvent.drop(box, carrying({ nodeId: "A", path: ["payload", "email"], type: "string" }));
    expect(onUpsert).toHaveBeenLastCalledWith(
      templated("Hi ", ref("payload"), ref("payload", "email")),
    );
    expect(onUpsert).toHaveBeenCalledTimes(2);
  });

  it("inserts at the cursor while it is being typed in", () => {
    const { onUpsert } = mount([templated("Hi !")]);
    const box = screen.getByLabelText("Message") as HTMLTextAreaElement;
    box.focus();
    box.setSelectionRange(3, 3);
    fireEvent.drop(box, carrying({ nodeId: "A", path: ["payload"], type: "object" }));
    expect(onUpsert).toHaveBeenLastCalledWith(templated("Hi ", ref("payload"), "!"));
  });

  it("refuses a dropped field it cannot read, and ignores anything else dropped", () => {
    const { onUpsert } = mount([templated("Hi ")]);
    const box = screen.getByLabelText("Message");
    fireEvent.drop(box, carrying({ nodeId: "B", path: ["echoed"], type: "string" }));
    expect(screen.getByText("{{Echo.echoed}} names nothing this step can read.")).toBeTruthy();
    fireEvent.drop(box, carrying(null));
    expect(onUpsert).not.toHaveBeenCalled();
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
});
