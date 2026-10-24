import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

import { BindingField } from "./binding-field";

/**
 * A field dragged from the step dialog's Input pane binds the parameter it is
 * dropped on - one that is not text, which takes it as a placeholder instead.
 */

const ITEM = {
  type: "object",
  title: "LoopItemOutput",
  properties: { item: { title: "Item" }, index: { type: "integer" } },
};
const LOOP_ITEM = makeDefinition({
  id: "loop.item",
  name: "Item",
  ports: [port("out", "output", ITEM)],
});
const catalog = makeCatalog([DEBUG_ECHO, LOOP_ITEM]);
const chain = graph({
  entry: "A",
  nodes: [node("A", "loop.item"), echo("B"), node("C", "loop.item")],
  edges: [edge("e", "A", "out", "B", "in"), edge("f", "B", "out", "C", "in")],
});

function carrying(field: unknown) {
  const raw = field === null ? "" : JSON.stringify(field);
  return {
    dataTransfer: {
      types: field === null ? ["text/plain"] : ["application/x-agenticos-step-field"],
      getData: () => raw,
    },
  };
}

function mount(disabled = false) {
  const onUpsert = vi.fn();
  render(
    <BindingField
      targetNodeId="B"
      targetField="message"
      name="message"
      schema={{ type: "integer", title: "Count" }}
      required={false}
      bindings={[]}
      graph={chain}
      catalog={catalog}
      disabled={disabled}
      onUpsert={onUpsert}
      onRemove={vi.fn()}
    />,
  );
  const target = screen.getByText("Count").closest(".relative") as HTMLElement;
  return { onUpsert, target };
}

describe("dropping a step's field on a parameter", () => {
  it("binds the setting to it, through a value with no declared shape", () => {
    const { onUpsert, target } = mount();
    fireEvent.drop(target, carrying({ nodeId: "A", path: ["item", "age"], type: "number" }));
    expect(onUpsert).toHaveBeenCalledWith({
      target_node_id: "B",
      target_field: "message",
      source: { kind: "node_output", node_id: "A", port: "out", field_path: ["item", "age"] },
    });
  });

  it("refuses a field of the wrong type, declared or seen in the run, and says why", () => {
    const { onUpsert, target } = mount();
    fireEvent.drop(target, carrying({ nodeId: "A", path: ["item", "name"], type: "string" }));
    expect(screen.getByText("“item.name” is not a value Count can take.")).toBeTruthy();
    fireEvent.drop(target, carrying({ nodeId: "B", path: ["echoed"], type: "string" }));
    expect(screen.getByText(/does not always run before it/)).toBeTruthy();
    expect(onUpsert).not.toHaveBeenCalled();
  });

  it("refuses a step that does not run before this one", () => {
    const { onUpsert, target } = mount();
    fireEvent.drop(target, carrying({ nodeId: "C", path: ["item"], type: "string" }));
    expect(screen.getByText(/does not always run before it/)).toBeTruthy();
    expect(onUpsert).not.toHaveBeenCalled();
  });

  it("marks where a field would land, and ignores anything else dragged", () => {
    const { onUpsert, target } = mount();
    fireEvent.dragOver(target, carrying(null));
    expect(target.className).not.toContain("ring-2");
    fireEvent.dragOver(target, carrying({ nodeId: "A", path: [], type: "object" }));
    expect(target.className).toContain("ring-2");
    fireEvent.dragLeave(target);
    expect(target.className).not.toContain("ring-2");
    fireEvent.drop(target, carrying(null));
    expect(onUpsert).not.toHaveBeenCalled();
  });

  it("takes nothing on a setting that cannot change", () => {
    const { target } = mount(true);
    fireEvent.dragOver(target, carrying({ nodeId: "A", path: [], type: "object" }));
    expect(target.className).not.toContain("ring-2");
  });
});
