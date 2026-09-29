import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Binding } from "@/lib/workflows/types";
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
import { candidateForBinding, sourceCandidates } from "./bindings";

/**
 * A source with no declared shape - a loop's current item, a trigger's payload -
 * has no fields to list, so the author types the path inside it, and a binding
 * saved through one is shown as picked, not as an empty picker.
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
  nodes: [node("A", "loop.item"), echo("B")],
  edges: [edge("e", "A", "out", "B", "in")],
});

function bound(path: string[]): Binding {
  return {
    target_node_id: "B",
    target_field: "message",
    source: { kind: "node_output", node_id: "A", port: "out", field_path: path },
  };
}

function mount(bindings: Binding[]) {
  const onUpsert = vi.fn();
  render(
    <BindingField
      targetNodeId="B"
      targetField="message"
      name="message"
      schema={{ type: "string", title: "Message" }}
      required={false}
      bindings={bindings}
      graph={chain}
      catalog={catalog}
      onUpsert={onUpsert}
      onRemove={vi.fn()}
    />,
  );
  return onUpsert;
}

describe("a binding through a value with no declared shape", () => {
  it("shows the value it reaches through and the path typed past it", () => {
    mount([bound(["item", "record_id"])]);
    expect(screen.getByRole("combobox", { name: "Source for Message" })).toHaveTextContent(
      "Item · A · out → item",
    );
    expect(screen.getByLabelText("Field inside it")).toHaveValue("record_id");
  });

  it("writes the typed path onto the binding, trimmed and split", () => {
    const onUpsert = mount([bound(["item"])]);
    const input = screen.getByLabelText("Field inside it");
    fireEvent.change(input, { target: { value: " fields . Email " } });
    fireEvent.blur(input);
    expect(onUpsert).toHaveBeenCalledWith(bound(["item", "fields", "Email"]));
  });
});

describe("candidateForBinding", () => {
  const candidates = sourceCandidates(chain, catalog, "B", { type: "string" });

  it("answers nothing for no binding, a literal, or a path through nothing it offers", () => {
    expect(candidateForBinding(candidates, undefined)).toBeUndefined();
    expect(
      candidateForBinding(candidates, {
        target_node_id: "B",
        target_field: "message",
        source: { kind: "literal", value: "x" },
      }),
    ).toBeUndefined();
    expect(candidateForBinding(candidates, bound(["index", "deeper"]))).toBeUndefined();
  });

  it("answers the exact candidate with nothing extra", () => {
    const found = candidateForBinding(candidates, bound(["item"]));
    expect(found?.candidate.fieldPath).toEqual(["item"]);
    expect(found?.extraPath).toEqual([]);
  });
});

describe("a free-form value typed as a literal", () => {
  function mountObject(bindings: Binding[] = []) {
    const onUpsert = vi.fn();
    const onRemove = vi.fn();
    render(
      <BindingField
        targetNodeId="B"
        targetField="values"
        name="values"
        schema={{ type: "object", additionalProperties: true, title: "Values" }}
        required={false}
        bindings={bindings}
        graph={chain}
        catalog={catalog}
        onUpsert={onUpsert}
        onRemove={onRemove}
      />,
    );
    return { onUpsert, onRemove, box: screen.getByLabelText("Values") };
  }

  it("shows the value as JSON and writes what is typed", () => {
    const { onUpsert, box } = mountObject([
      { target_node_id: "B", target_field: "values", source: { kind: "literal", value: { a: 1 } } },
    ]);
    expect(box).toHaveValue('{\n  "a": 1\n}');
    fireEvent.change(box, { target: { value: '{"Score": 100}' } });
    fireEvent.blur(box);
    expect(onUpsert).toHaveBeenCalledWith({
      target_node_id: "B",
      target_field: "values",
      source: { kind: "literal", value: { Score: 100 } },
    });
  });

  it("refuses JSON that does not parse, and clears an emptied box", () => {
    const { onUpsert, onRemove, box } = mountObject();
    fireEvent.change(box, { target: { value: "{nope" } });
    fireEvent.blur(box);
    expect(screen.getByText("This is not valid JSON, so it was not saved.")).toBeTruthy();
    expect(onUpsert).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "  " } });
    fireEvent.blur(box);
    expect(onRemove).toHaveBeenCalledWith("B", "values");
    expect(screen.queryByText("This is not valid JSON, so it was not saved.")).toBeNull();
  });
});
