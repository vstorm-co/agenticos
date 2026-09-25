import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Binding } from "@/lib/workflows/types";
import {
  DEBUG_ECHO,
  DEBUG_ECHO_OUTPUT,
  STRING,
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

describe("BindingField literal mode", () => {
  it("stores a typed value as a literal binding", async () => {
    const { onUpsert } = mount();
    await userEvent.type(screen.getByLabelText("Message"), "h");
    expect(onUpsert).toHaveBeenLastCalledWith({
      target_node_id: "B",
      target_field: "message",
      source: { kind: "literal", value: "h" },
    });
  });

  it("removes the binding when the value is cleared", async () => {
    const { onRemove } = mount({
      bindings: [
        { target_node_id: "B", target_field: "message", source: { kind: "literal", value: "x" } },
      ],
    });
    await userEvent.clear(screen.getByLabelText("Message"));
    expect(onRemove).toHaveBeenCalledWith("B", "message");
  });

  it("shows a field error in the wrapped control", () => {
    mount({ error: "Required" });
    expect(screen.getByText("Required")).toBeVisible();
  });
});

describe("BindingField binding mode", () => {
  it("toggles to a source picker and stores the chosen output", async () => {
    const { onUpsert } = mount({ schema: DEBUG_ECHO_OUTPUT });
    await userEvent.click(
      screen.getByRole("switch", { name: "Bind DebugEchoOutput to another node" }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Source for DebugEchoOutput" }));
    await userEvent.click(screen.getByRole("option", { name: /out/ }));
    expect(onUpsert).toHaveBeenCalledWith({
      target_node_id: "B",
      target_field: "message",
      source: { kind: "node_output", node_id: "A", port: "out", field_path: [] },
    });
  });

  it("drops an existing literal when switched to binding mode", async () => {
    const { onRemove } = mount({
      schema: DEBUG_ECHO_OUTPUT,
      bindings: [
        {
          target_node_id: "B",
          target_field: "message",
          source: { kind: "literal", value: "old" },
        },
      ],
    });
    await userEvent.click(
      screen.getByRole("switch", { name: "Bind DebugEchoOutput to another node" }),
    );
    expect(onRemove).toHaveBeenCalledWith("B", "message");
  });

  it("shows the current source and clears it when switched back to literal", async () => {
    const { onRemove } = mount({
      schema: DEBUG_ECHO_OUTPUT,
      bindings: [
        {
          target_node_id: "B",
          target_field: "message",
          source: { kind: "node_output", node_id: "A", port: "out", field_path: [] },
        },
      ],
    });
    // Starts in binding mode because a node-output binding exists.
    const toggle = screen.getByRole("switch", { name: "Bind DebugEchoOutput to another node" });
    expect(toggle).toBeChecked();
    await userEvent.click(toggle);
    expect(onRemove).toHaveBeenCalledWith("B", "message");
  });

  it("says so when no upstream output is compatible", async () => {
    mount({ schema: STRING });
    await userEvent.click(screen.getByRole("switch", { name: "Bind Message to another node" }));
    expect(screen.getByText("No compatible upstream outputs")).toBeVisible();
  });

  it("shows a field error under the source picker", async () => {
    mount({ schema: DEBUG_ECHO_OUTPUT, error: "Unfilled" });
    await userEvent.click(
      screen.getByRole("switch", { name: "Bind DebugEchoOutput to another node" }),
    );
    expect(screen.getByText("Unfilled")).toBeVisible();
  });

  it("marks a required field in binding mode", async () => {
    mount({ schema: DEBUG_ECHO_OUTPUT, required: true });
    await userEvent.click(
      screen.getByRole("switch", { name: "Bind DebugEchoOutput to another node" }),
    );
    expect(screen.getByText("*")).toBeVisible();
  });
});
