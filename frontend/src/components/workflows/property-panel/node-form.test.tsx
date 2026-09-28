import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Binding, NodeDefinition } from "@/lib/workflows/types";
import {
  graph,
  makeCatalog,
  makeDefinition,
  node,
} from "@/components/workflows/validation/fixtures";

import { NodeForm } from "./node-form";
import type { Schema } from "./schema-model";

// The resource pickers are covered in their own suite; here they stand in as
// simple controls so the form's wiring — which picker, and what it writes — is
// what is under test.
vi.mock("@/components/workflows/pickers", () => ({
  AgentVersionPicker: ({
    value,
    onChange,
    error,
  }: {
    value: { agent_id: string | null };
    onChange: (v: unknown) => void;
    error?: string;
  }) => (
    <div>
      <button
        type="button"
        aria-label="set-agent"
        onClick={() => onChange({ agent_id: "ag", version_id: "v" })}
      />
      <span>{value.agent_id ?? "agent-none"}</span>
      {error !== undefined && <span>{error}</span>}
    </div>
  ),
  TableColumnPicker: ({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) => (
    <div>
      <button
        type="button"
        aria-label="set-table"
        onClick={() =>
          onChange({ kind: "table", table_id: "t", column_ids: null, schema_version: 1 })
        }
      />
      <button type="button" aria-label="clear-table" onClick={() => onChange(null)} />
      <span>{value === null ? "table-none" : "table-set"}</span>
    </div>
  ),
  SecretPicker: ({ value, onChange }: { value: string | null; onChange: (v: unknown) => void }) => (
    <div>
      <button type="button" aria-label="set-secret" onClick={() => onChange("sec")} />
      <button type="button" aria-label="clear-secret" onClick={() => onChange(null)} />
      <span>{value ?? "secret-none"}</span>
    </div>
  ),
}));

const CONFIG_SCHEMA: Schema = {
  type: "object",
  properties: {
    message: { type: "string", title: "Message" },
    agent: { "x-resource": "agent", title: "Agent" },
    secret: { "x-resource": "secret", title: "Secret" },
    table: { "x-resource": "table", title: "Table" },
    dynamic: { type: "string", "x-bindable": true, title: "Dynamic" },
    nested: {
      type: "object",
      title: "Nested",
      properties: { inner: { type: "string", title: "Inner" } },
    },
    mappings: {
      type: "array",
      title: "Mappings",
      items: {
        type: "object",
        title: "Row",
        properties: {
          column: { type: "string", title: "Column" },
          value: { type: "string", "x-bindable": true, title: "Value" },
        },
      },
    },
    result: {
      title: "Result",
      oneOf: [
        {
          type: "object",
          title: "Text",
          properties: { kind: { const: "text" }, text: { type: "string", title: "Text field" } },
        },
        {
          type: "object",
          title: "Number",
          properties: { kind: { const: "number" }, num: { type: "integer", title: "Num" } },
        },
      ],
    },
  },
};

const INPUT_SCHEMA: Schema = {
  type: "object",
  properties: {
    in_scalar: { type: "string", title: "In scalar" },
    in_group: {
      type: "object",
      title: "Group",
      properties: { g: { type: "string", title: "G" } },
    },
  },
};

const definition = makeDefinition({
  id: "test.node",
  name: "Test",
  config_schema: CONFIG_SCHEMA,
  input_schema: INPUT_SCHEMA,
});

function renderForm(
  options: {
    config?: Record<string, unknown>;
    bindings?: Binding[];
    errors?: Map<string, string>;
    definition?: NodeDefinition;
    disabled?: boolean;
  } = {},
) {
  const def = options.definition ?? definition;
  const instance = node("N", def.id, options.config ?? {});
  const bindings = options.bindings ?? [];
  const workflow = graph({ entry: "N", nodes: [instance], bindings });
  const updateNodeConfig = vi.fn();
  const upsertBinding = vi.fn();
  const removeBinding = vi.fn();
  render(
    <NodeForm
      definition={def}
      node={instance}
      graph={workflow}
      catalog={makeCatalog([def])}
      bindings={bindings}
      errors={options.errors ?? new Map()}
      disabled={options.disabled}
      updateNodeConfig={updateNodeConfig}
      upsertBinding={upsertBinding}
      removeBinding={removeBinding}
    />,
  );
  return { updateNodeConfig, upsertBinding, removeBinding };
}

describe("NodeForm sections", () => {
  it("renders a config section and an input section", () => {
    renderForm();
    expect(screen.getByText("Configuration")).toBeVisible();
    expect(screen.getByText("Inputs")).toBeVisible();
  });

  it("shows an empty message when a node has no fields", () => {
    renderForm({ definition: makeDefinition({ id: "bare" }) });
    expect(screen.getByText("This node has no configurable fields.")).toBeVisible();
  });
});

describe("config leaves", () => {
  it("writes a scalar literal into config", async () => {
    const { updateNodeConfig } = renderForm();
    await userEvent.type(screen.getByLabelText("Message"), "h");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { message: "h" });
  });

  it("shows a field-scoped error on a scalar leaf", () => {
    renderForm({ errors: new Map([["message", "Too short"]]) });
    expect(screen.getByText("Too short")).toBeVisible();
  });

  it("pins an agent through the agent picker", async () => {
    const { updateNodeConfig } = renderForm();
    await userEvent.click(screen.getByLabelText("set-agent"));
    expect(updateNodeConfig).toHaveBeenCalledWith("N", {
      agent: { agent_id: "ag", version_id: "v" },
    });
  });

  it("shows an existing agent pin's value", () => {
    renderForm({ config: { agent: { agent_id: "ag", version_id: "v" } } });
    expect(screen.getByText("ag")).toBeVisible();
  });

  it("pins and clears a table", async () => {
    const { updateNodeConfig } = renderForm({
      config: { table: { kind: "table", table_id: "t", column_ids: null, schema_version: 1 } },
    });
    expect(screen.getByText("table-set")).toBeVisible();
    await userEvent.click(screen.getByLabelText("set-table"));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {
      table: { kind: "table", table_id: "t", column_ids: null, schema_version: 1 },
    });
    await userEvent.click(screen.getByLabelText("clear-table"));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("pins and clears a secret", async () => {
    const { updateNodeConfig } = renderForm();
    await userEvent.click(screen.getByLabelText("set-secret"));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { secret: "sec" });
    await userEvent.click(screen.getByLabelText("clear-secret"));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("renders an x-bindable config leaf as a binding, writing bindings not config", async () => {
    const { updateNodeConfig, upsertBinding } = renderForm();
    await userEvent.type(screen.getByLabelText("Dynamic"), "h");
    expect(upsertBinding).toHaveBeenLastCalledWith({
      target_node_id: "N",
      target_field: "dynamic",
      source: { kind: "literal", value: "h" },
    });
    // config is untouched by a bindable leaf
    expect(updateNodeConfig).not.toHaveBeenCalled();
  });

  it("recurses into a nested object", async () => {
    const { updateNodeConfig } = renderForm();
    await userEvent.type(screen.getByLabelText("Inner"), "h");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { nested: { inner: "h" } });
  });
});

describe("array of objects", () => {
  const twoRows = {
    config: {
      mappings: [{ column: "a" }, { column: "b" }],
    },
    bindings: [
      {
        target_node_id: "N",
        target_field: "mappings/0/value",
        source: { kind: "literal", value: "x" },
      },
      {
        target_node_id: "N",
        target_field: "mappings/1/value",
        source: { kind: "literal", value: "y" },
      },
    ] as Binding[],
  };

  it("adds a row", async () => {
    const { updateNodeConfig } = renderForm({ config: { mappings: [{ column: "a" }] } });
    await userEvent.click(screen.getByRole("button", { name: "Add row" }));
    expect(updateNodeConfig).toHaveBeenCalledWith("N", { mappings: [{ column: "a" }, {}] });
  });

  it("removes a row and rebases later bindings", async () => {
    const { updateNodeConfig, removeBinding, upsertBinding } = renderForm(twoRows);
    await userEvent.click(screen.getByRole("button", { name: "Remove row 1" }));
    expect(removeBinding).toHaveBeenCalledWith("N", "mappings/0/value");
    expect(removeBinding).toHaveBeenCalledWith("N", "mappings/1/value");
    expect(upsertBinding).toHaveBeenCalledWith({
      target_node_id: "N",
      target_field: "mappings/0/value",
      source: { kind: "literal", value: "y" },
    });
    expect(updateNodeConfig).toHaveBeenCalledWith("N", { mappings: [{ column: "b" }] });
  });

  it("drops the whole array when the last row is removed", async () => {
    const { updateNodeConfig } = renderForm({ config: { mappings: [{ column: "only" }] } });
    await userEvent.click(screen.getByRole("button", { name: "Remove row 1" }));
    expect(updateNodeConfig).toHaveBeenCalledWith("N", {});
  });

  it("reorders rows and disables the ends", async () => {
    const { updateNodeConfig } = renderForm(twoRows);
    expect(screen.getByRole("button", { name: "Move row 1 up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move row 2 down" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Move row 1 down" }));
    expect(updateNodeConfig).toHaveBeenCalledWith("N", {
      mappings: [{ column: "b" }, { column: "a" }],
    });
    await userEvent.click(screen.getByRole("button", { name: "Move row 2 up" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {
      mappings: [{ column: "b" }, { column: "a" }],
    });
  });

  it("disables the reorder and add controls when the form is disabled", () => {
    renderForm({ ...twoRows, disabled: true });
    expect(screen.getByRole("button", { name: "Move row 1 down" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove row 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add row" })).toBeDisabled();
  });

  it("edits a non-bindable field within a row", async () => {
    const { updateNodeConfig } = renderForm({ config: { mappings: [{ column: "" }] } });
    await userEvent.type(screen.getByLabelText("Column"), "c");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { mappings: [{ column: "c" }] });
  });
});

describe("discriminated union", () => {
  it("renders only the selector when no branch is chosen", () => {
    renderForm();
    expect(screen.getByRole("combobox", { name: "Result type" })).toBeVisible();
    expect(screen.queryByLabelText("Text field")).toBeNull();
  });

  it("renders the chosen branch's fields and edits them", async () => {
    const { updateNodeConfig } = renderForm({ config: { result: { kind: "text" } } });
    await userEvent.type(screen.getByLabelText("Text field"), "h");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { result: { kind: "text", text: "h" } });
  });

  it("switches branch, discarding the old shape and its bindings", async () => {
    const { updateNodeConfig, removeBinding } = renderForm({
      config: { result: { kind: "text" } },
      bindings: [
        {
          target_node_id: "N",
          target_field: "result/text",
          source: { kind: "literal", value: "x" },
        },
      ],
    });
    await userEvent.click(screen.getByRole("combobox", { name: "Result type" }));
    await userEvent.click(screen.getByRole("option", { name: "Number" }));
    expect(removeBinding).toHaveBeenCalledWith("N", "result/text");
    expect(updateNodeConfig).toHaveBeenCalledWith("N", { result: { kind: "number" } });
  });
});

describe("input fields", () => {
  it("binds a scalar input", async () => {
    const { upsertBinding } = renderForm();
    await userEvent.type(screen.getByLabelText("In scalar"), "h");
    expect(upsertBinding).toHaveBeenLastCalledWith({
      target_node_id: "N",
      target_field: "in_scalar",
      source: { kind: "literal", value: "h" },
    });
  });

  it("recurses a nested input group, keying the binding by path", async () => {
    const { upsertBinding } = renderForm();
    expect(screen.getByText("Group")).toBeVisible();
    await userEvent.type(screen.getByLabelText("G"), "h");
    expect(upsertBinding).toHaveBeenLastCalledWith({
      target_node_id: "N",
      target_field: "in_group/g",
      source: { kind: "literal", value: "h" },
    });
  });
});
