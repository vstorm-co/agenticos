import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Binding } from "@/lib/workflows/types";
import {
  DEBUG_ECHO,
  DEBUG_ECHO_OUTPUT,
  INTEGER,
  echo,
  edge,
  graph,
  makeCatalog,
} from "@/components/workflows/validation/fixtures";

import { BindingField } from "./binding-field";
import type { Schema } from "./schema-model";

const catalog = makeCatalog([DEBUG_ECHO]);
const chain = graph({
  entry: "A",
  nodes: [echo("A"), echo("B")],
  edges: [edge("e", "A", "out", "B", "in")],
});

function mount(
  props: Partial<{
    schema: Schema;
    targetField: string;
    bindings: Binding[];
    error: string;
    disabled: boolean;
    required: boolean;
  }> = {},
) {
  const onUpsert = vi.fn();
  const onRemove = vi.fn();
  render(
    <BindingField
      targetNodeId="B"
      targetField={props.targetField ?? "message"}
      name="message"
      schema={props.schema ?? { type: "string", title: "Message" }}
      required={props.required ?? false}
      bindings={props.bindings ?? []}
      graph={chain}
      catalog={catalog}
      error={props.error}
      disabled={props.disabled}
      onUpsert={onUpsert}
      onRemove={onRemove}
    />,
  );
  return { onUpsert, onRemove };
}

describe("a parameter that is not text", () => {
  it("stores a typed value, and removes it when cleared", async () => {
    const { onUpsert } = mount({ schema: { ...INTEGER, title: "Count" } });
    await userEvent.type(screen.getByLabelText("Count"), "3");
    expect(onUpsert).toHaveBeenLastCalledWith({
      target_node_id: "B",
      target_field: "message",
      source: { kind: "literal", value: 3 },
    });
  });

  it("removes a typed value when it is cleared", async () => {
    const { onRemove } = mount({
      schema: { ...INTEGER, title: "Count" },
      bindings: [
        { target_node_id: "B", target_field: "message", source: { kind: "literal", value: 3 } },
      ],
    });
    await userEvent.clear(screen.getByLabelText("Count"));
    expect(onRemove).toHaveBeenCalledWith("B", "message");
  });

  it("takes its value from an earlier step through Data", async () => {
    const { onUpsert } = mount({ schema: DEBUG_ECHO_OUTPUT });
    await userEvent.click(
      screen.getByRole("button", { name: "Take DebugEchoOutput from an earlier step" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: /everything it hands on/ }));
    expect(onUpsert).toHaveBeenCalledWith({
      target_node_id: "B",
      target_field: "message",
      source: { kind: "node_output", node_id: "A", port: "out", field_path: [] },
    });
  });

  it("says so when no earlier step hands on anything it can take", async () => {
    mount({ schema: INTEGER });
    await userEvent.click(screen.getByRole("button", { name: /from an earlier step/ }));
    expect(screen.getByText("No compatible upstream outputs")).toBeVisible();
  });

  it("offers no Data when it cannot be edited", () => {
    mount({ schema: INTEGER, disabled: true });
    expect(screen.queryByRole("button", { name: /from an earlier step/ })).toBeNull();
  });
});

describe("a parameter read from an earlier step", () => {
  const readFrom = (nodeId: string, path: string[] = ["echoed"]): Binding => ({
    target_node_id: "B",
    target_field: "message",
    source: { kind: "node_output", node_id: nodeId, port: "out", field_path: path },
  });
  const bound = readFrom("A");

  it("shows the step and field it reads, and what kind of value it is", () => {
    mount({ schema: { type: "string", title: "Message" }, bindings: [bound] });
    // Two Echo steps: the name tells this one apart the way the canvas does.
    expect(screen.getByText(/^Echo · \w+ › echoed$/)).toBeTruthy();
    expect(screen.getByText("text")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
  });

  it("goes back to a typed value with the x", async () => {
    const { onRemove } = mount({ schema: { type: "string", title: "Message" }, bindings: [bound] });
    await userEvent.click(screen.getByRole("button", { name: "Type Message instead" }));
    expect(onRemove).toHaveBeenCalledWith("B", "message");
  });

  it("changes the field it reads through Data", async () => {
    const { onUpsert } = mount({ schema: DEBUG_ECHO_OUTPUT, bindings: [bound] });
    await userEvent.click(screen.getByRole("button", { name: /from an earlier step/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: /everything it hands on/ }));
    expect(onUpsert).toHaveBeenLastCalledWith({
      ...bound,
      source: { ...bound.source, field_path: [] },
    });
  });

  it("says when the step it read from is no longer before this one", () => {
    mount({
      schema: { type: "string", title: "Message" },
      bindings: [readFrom("gone")],
    });
    expect(screen.getByText("A step that no longer comes before this one")).toBeTruthy();
  });

  it("marks a required field and shows its error", () => {
    mount({
      schema: { type: "string", title: "Message" },
      bindings: [bound],
      required: true,
      error: "Unfilled",
    });
    expect(screen.getByText("*")).toBeVisible();
    expect(screen.getByText("Unfilled")).toBeVisible();
  });

  it("reads nothing but shows its source when it cannot be edited", () => {
    mount({ schema: { type: "string", title: "Message" }, bindings: [bound], disabled: true });
    expect(screen.getByText(/› echoed$/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Type Message instead" })).toBeNull();
  });
});
