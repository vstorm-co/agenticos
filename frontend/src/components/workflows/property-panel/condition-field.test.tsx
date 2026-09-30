import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  edge,
  graph,
  makeCatalog,
  makeDefinition,
  node,
  port,
} from "@/components/workflows/validation/fixtures";
import type { Binding } from "@/lib/workflows/types";

import { ConditionField, conditionFields } from "./condition-field";

function Harness({
  initial,
  onChange,
  disabled,
  root = "item",
}: {
  initial?: string;
  onChange: (value: string | undefined) => void;
  disabled?: boolean;
  root?: "item" | "value";
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ConditionField
        root={root}
        label="Condition"
        required
        hint="A JMESPath expression"
        value={value}
        disabled={disabled}
        fields={["score", "name"]}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
      />
      <button type="button" onClick={() => setValue("item.done")}>
        undo
      </button>
    </>
  );
}

describe("ConditionField", () => {
  it("builds a condition from a field, a check and a value", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    expect(screen.getByText("*")).toBeTruthy();

    await userEvent.type(screen.getByLabelText("Field of condition 1"), "score");
    // No value yet: nothing to write.
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    await userEvent.click(screen.getByRole("combobox", { name: "Check of condition 1" }));
    await userEvent.click(screen.getByRole("option", { name: "is at least" }));
    await userEvent.type(screen.getByLabelText("Value of condition 1"), "50");
    expect(onChange).toHaveBeenLastCalledWith("item.score >= `50`");
    // The fields the step reads are suggested.
    expect(document.querySelectorAll("datalist option")).toHaveLength(2);
  });

  it("joins several conditions by all or any, and removes one", async () => {
    const onChange = vi.fn();
    render(<Harness initial="item.score >= `50`" onChange={onChange} />);
    expect(screen.getByLabelText("Field of condition 1")).toHaveValue("score");
    expect(screen.getByRole("button", { name: "Remove condition 1" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Add a condition" }));
    await userEvent.type(screen.getByLabelText("Field of condition 2"), "name");
    await userEvent.click(screen.getByRole("combobox", { name: "Check of condition 2" }));
    await userEvent.click(screen.getByRole("option", { name: "is not empty" }));
    expect(screen.queryByLabelText("Value of condition 2")).toBeNull();
    expect(onChange).toHaveBeenLastCalledWith("item.score >= `50` && item.name");

    await userEvent.click(screen.getByRole("combobox", { name: "How the conditions combine" }));
    await userEvent.click(screen.getByRole("option", { name: "any" }));
    expect(onChange).toHaveBeenLastCalledWith("item.score >= `50` || item.name");

    await userEvent.click(screen.getByRole("button", { name: "Remove condition 1" }));
    expect(onChange).toHaveBeenLastCalledWith("item.name");
  });

  it("edits an expression it did not write as the expression it is", async () => {
    const onChange = vi.fn();
    render(<Harness initial="length(item.tags) > `2`" onChange={onChange} />);
    const box = screen.getByLabelText(/^Condition/);
    expect(box).toHaveValue("length(item.tags) > `2`");
    expect(screen.getByText("A JMESPath expression")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Build it from conditions" })).toBeDisabled();

    fireEvent.change(box, { target: { value: "item.ok" } });
    expect(onChange).toHaveBeenLastCalledWith("item.ok");
    await userEvent.click(screen.getByRole("button", { name: "Build it from conditions" }));
    expect(screen.getByLabelText("Field of condition 1")).toHaveValue("ok");

    await userEvent.click(screen.getByRole("button", { name: "Write it as an expression" }));
    fireEvent.change(screen.getByLabelText(/^Condition/), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    await userEvent.click(screen.getByRole("button", { name: "Build it from conditions" }));
    expect(screen.getByLabelText("Field of condition 1")).toHaveValue("");
  });

  it("shows a condition written elsewhere, such as an undo", async () => {
    render(<Harness initial="item.score >= `50`" onChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "undo" }));
    expect(screen.getByLabelText("Field of condition 1")).toHaveValue("done");
  });

  it("reads a value's condition over the value, and offers nothing to change read-only", () => {
    render(<Harness root="value" initial="value.status == 'ok'" onChange={vi.fn()} disabled />);
    expect(screen.getByLabelText("Field of condition 1")).toHaveValue("status");
    expect(screen.getByLabelText("Field of condition 1")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Add a condition" })).toBeNull();
  });
});

describe("conditionFields", () => {
  const SOURCE = makeDefinition({
    id: "test.source",
    ports: [
      port("out", "output", {
        type: "object",
        properties: {
          records: { type: "array", items: {} },
          lead: { type: "object", properties: { status: { type: "string" } } },
        },
      }),
    ],
  });
  const catalog = makeCatalog([SOURCE]);
  const chain = graph({
    entry: "A",
    nodes: [node("A", "test.source"), node("B", "test.source")],
    edges: [edge("e", "A", "out", "B", "in")],
  });
  const reading = (field: string, path: string[]): Binding[] => [
    {
      target_node_id: "B",
      target_field: field,
      source: { kind: "node_output", node_id: "A", port: "out", field_path: path },
    },
  ];

  it("names the fields of the first item a list held in the last run", () => {
    const stepData = { A: { output: { records: [{ score: 1, name: "Ada" }] } } };
    expect(
      conditionFields("item", "B", chain, catalog, reading("items", ["records"]), stepData),
    ).toEqual(["score", "name"]);
    // Nothing seen yet, and a list declares no item fields to suggest.
    expect(conditionFields("item", "B", chain, catalog, reading("items", ["records"]), {})).toEqual(
      [],
    );
  });

  it("names a value's fields as seen, or as the step before declares them", () => {
    const pinned = graph({
      entry: "A",
      nodes: [
        { ...node("A", "test.source"), pinned_output: { lead: { owner: "x" } } },
        node("B", "test.source"),
      ],
      edges: [],
    });
    expect(conditionFields("value", "B", pinned, catalog, reading("value", ["lead"]), {})).toEqual([
      "owner",
    ]);
    expect(conditionFields("value", "B", chain, catalog, reading("value", ["lead"]), {})).toEqual([
      "status",
    ]);
  });

  it("names nothing for a value not read from a step, or from a step it does not know", () => {
    expect(conditionFields("value", "B", chain, catalog, [], {})).toEqual([]);
    const literal: Binding[] = [
      { target_node_id: "B", target_field: "value", source: { kind: "literal", value: 1 } },
    ];
    expect(conditionFields("value", "B", chain, catalog, literal, {})).toEqual([]);
    expect(
      conditionFields("value", "B", chain, makeCatalog([]), reading("value", ["lead"]), {}),
    ).toEqual([]);
  });
});
