import { fireEvent, render, screen } from "@testing-library/react";
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
  ChannelBotPicker: ({
    value,
    onChange,
  }: {
    value: string | null;
    onChange: (v: unknown) => void;
  }) => (
    <div>
      <button type="button" aria-label="set-bot" onClick={() => onChange("bot-1")} />
      <button type="button" aria-label="clear-bot" onClick={() => onChange(null)} />
      <span>{value ?? "bot-none"}</span>
    </div>
  ),
  WorkflowPicker: ({
    value,
    onChange,
  }: {
    value: string | null;
    onChange: (v: unknown) => void;
  }) => (
    <div>
      <button type="button" aria-label="set-workflow" onClick={() => onChange("wf-1")} />
      <button type="button" aria-label="clear-workflow" onClick={() => onChange(null)} />
      <span>{value ?? "workflow-none"}</span>
    </div>
  ),
  SandboxConnectionPicker: ({
    value,
    onChange,
  }: {
    value: string | null;
    onChange: (v: unknown) => void;
  }) => (
    <div>
      <button type="button" aria-label="set-host" onClick={() => onChange("host-1")} />
      <button type="button" aria-label="default-host" onClick={() => onChange(null)} />
      <span>{value ?? "host-default"}</span>
    </div>
  ),
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
      {(value as { column_ids?: unknown } | null)?.column_ids === null && <span>columns-all</span>}
    </div>
  ),
  SecretPicker: ({
    value,
    onChange,
    kind,
    label,
  }: {
    value: string | null;
    onChange: (v: unknown) => void;
    kind?: string;
    label?: string;
  }) => (
    <div>
      <span>{`picker-label:${label ?? "own"}`}</span>
      <button type="button" aria-label="set-secret" onClick={() => onChange("sec")} />
      <button type="button" aria-label="clear-secret" onClick={() => onChange(null)} />
      <span>{value ?? "secret-none"}</span>
      <span>{`secret-kind:${kind ?? "any"}`}</span>
    </div>
  ),
  CollectionPicker: ({
    selectedIds,
    onToggle,
  }: {
    selectedIds: string[];
    onToggle: (id: string) => void;
  }) => (
    <div>
      <button type="button" aria-label="toggle-kb-a" onClick={() => onToggle("kb-a")} />
      <span>{`collections:${selectedIds.join(",") || "none"}`}</span>
    </div>
  ),
}));

vi.mock("@/components/orgs/member-picker", () => ({
  MemberPicker: ({
    selected,
    onToggle,
    label,
  }: {
    selected: string[];
    onToggle: (id: string) => void;
    label: (count: number) => string;
  }) => (
    <div>
      <button type="button" aria-label="toggle-member-u1" onClick={() => onToggle("u1")} />
      <span>{label(selected.length)}</span>
    </div>
  ),
}));

vi.mock("@/hooks", () => ({
  useKnowledgeBases: () => ({ kbs: [] }),
  useMembers: () => ({ members: [] }),
}));

const CONFIG_SCHEMA: Schema = {
  type: "object",
  properties: {
    message: { type: "string", title: "Message" },
    agent: { "x-resource": "agent", title: "Agent" },
    secret: { "x-resource": "secret", title: "Secret" },
    table: { "x-resource": "table", title: "Table" },
    credential: { "x-resource": "secret", "x-secret-kind": "http_credential", title: "Credential" },
    collections: { "x-resource": "collection", title: "Collections" },
    recipients: { "x-resource": "member", title: "Recipients" },
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
    /** Leave the optional settings folded, as a step first opens. */
    folded?: boolean;
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
  // Every field these tests read: the optional ones wait under "More options".
  const more = screen.queryByRole("button", { name: /more option/ });
  if (!options.folded && more !== null) fireEvent.click(more);
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

  it("says how a trigger with nothing to set starts a run, in place of the empty message", () => {
    renderForm({ definition: makeDefinition({ id: "trigger.webhook", category: "triggers" }) });
    expect(screen.getByText(/its own address and signing secret/)).toBeVisible();
  });

  it("edits an agent step's answer shape as the Builder edits an agent's own", async () => {
    const agentRun = makeDefinition({
      id: "agent.run",
      config_schema: {
        type: "object",
        properties: { structured_output_schema: { type: "object" } },
      } as Schema,
    });
    const shaped = { type: "object", properties: { score: { type: "integer" } }, required: [] };
    const { updateNodeConfig } = renderForm({
      definition: agentRun,
      config: { structured_output_schema: shaped },
    });
    expect(screen.getByDisplayValue("score")).toBeVisible();

    await userEvent.click(screen.getByRole("combobox", { name: "It answers" }));
    await userEvent.click(screen.getByRole("option", { name: "As the agent answers" }));
    // Back to the agent's own: the override leaves the config altogether.
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("opens an agent step with no override on the agent's own format", () => {
    const agentRun = makeDefinition({
      id: "agent.run",
      config_schema: {
        type: "object",
        properties: { structured_output_schema: { type: "object" } },
      } as Schema,
    });
    renderForm({ definition: agentRun });
    expect(screen.getByText("As the agent answers")).toBeVisible();
  });

  it("names a picker by its field's own title, and never labels it twice", () => {
    renderForm({
      definition: makeDefinition({
        id: "decide.yes_no",
        config_schema: {
          type: "object",
          properties: {
            secret_id: { "x-resource": "secret", title: "TypeSafe key" },
            other_id: { "x-resource": "secret", title: "Other Id" },
          },
        } as Schema,
      }),
    });
    expect(screen.getByText("picker-label:TypeSafe key")).toBeVisible();
    // A title Pydantic made of the name says less than the picker's own label.
    expect(screen.getByText("picker-label:own")).toBeVisible();
    expect(screen.queryByText("TypeSafe key")).toBeNull();
    expect(screen.queryByText("Other Id")).toBeNull();
  });

  it("picks a script step's sandbox host, and goes back to the default", async () => {
    const scriptStep = makeDefinition({
      id: "code.javascript.sandbox",
      config_schema: {
        type: "object",
        properties: {
          connection_id: { "x-resource": "sandbox_connection", title: "Sandbox host" },
        },
      } as Schema,
    });
    const { updateNodeConfig } = renderForm({ definition: scriptStep });
    expect(screen.getByText("host-default")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "set-host" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { connection_id: "host-1" });
    await userEvent.click(screen.getByRole("button", { name: "default-host" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("pins a channel step's bot through the bot picker, and clears it", async () => {
    const channelStep = makeDefinition({
      id: "channel.send",
      config_schema: {
        type: "object",
        properties: { bot_id: { "x-resource": "channel_bot", title: "Bot" } },
      } as Schema,
    });
    const { updateNodeConfig } = renderForm({
      definition: channelStep,
      config: { bot_id: "bot-0" },
    });
    expect(screen.getByText("bot-0")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "set-bot" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { bot_id: "bot-1" });
    await userEvent.click(screen.getByRole("button", { name: "clear-bot" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("names the workflow a Run a workflow step runs through the workflow picker", async () => {
    const callStep = makeDefinition({
      id: "workflow.run",
      config_schema: {
        type: "object",
        properties: { workflow_id: { "x-resource": "workflow", title: "Workflow" } },
      } as Schema,
    });
    const { updateNodeConfig } = renderForm({ definition: callStep });
    expect(screen.getByText("workflow-none")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "set-workflow" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { workflow_id: "wf-1" });
    await userEvent.click(screen.getByRole("button", { name: "clear-workflow" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("sets a Schedule trigger up in its own words rather than as raw fields", () => {
    renderForm({ definition: makeDefinition({ id: "trigger.schedule", category: "triggers" }) });
    expect(screen.getByLabelText("Every")).toBeVisible();
    expect(screen.queryByText("Configuration")).toBeNull();
  });

  it.each([
    ["trigger.manual", /Start it with Run/],
    ["core.input", /POST \/api\/v1\/workflow-runs/],
  ])("gives %s its typed input fields, under how it starts", (id, hint) => {
    renderForm({ definition: makeDefinition({ id, category: "triggers" }) });
    expect(screen.getByText(hint)).toBeVisible();
    expect(screen.getByRole("button", { name: "Add field" })).toBeVisible();
    expect(screen.queryByText("Configuration")).toBeNull();
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

  it("reads a pinned table that leaves out what the server defaults", async () => {
    const { updateNodeConfig } = renderForm({
      config: { table: { table_id: "t", schema_version: 1 } },
    });
    expect(screen.getByText("table-set")).toBeVisible();
    expect(screen.getByText("columns-all")).toBeVisible();
    await userEvent.click(screen.getByLabelText("set-table"));
    expect(updateNodeConfig).toHaveBeenCalled();
  });

  it("pins and clears a secret", async () => {
    const { updateNodeConfig } = renderForm();
    // The first of the form's two secret leaves: `secret`, then `credential`.
    const [setSecret] = screen.getAllByLabelText("set-secret");
    const [clearSecret] = screen.getAllByLabelText("clear-secret");
    await userEvent.click(setSecret as HTMLElement);
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { secret: "sec" });
    await userEvent.click(clearSecret as HTMLElement);
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("narrows a secret leaf to the vault kind it names", () => {
    renderForm();
    expect(screen.getByText("secret-kind:http_credential")).toBeVisible();
    expect(screen.getByText("secret-kind:any")).toBeVisible();
  });

  it("adds and removes collections as a list of ids", async () => {
    const { updateNodeConfig } = renderForm({ config: { collections: ["kb-b"] } });
    expect(screen.getByText("collections:kb-b")).toBeVisible();
    await userEvent.click(screen.getByLabelText("toggle-kb-a"));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { collections: ["kb-b", "kb-a"] });
  });

  it("removes a collection already chosen, and ignores what is not an id", async () => {
    const { updateNodeConfig } = renderForm({ config: { collections: ["kb-a", 7] } });
    await userEvent.click(screen.getByLabelText("toggle-kb-a"));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { collections: [] });
  });

  it("chooses recipients by member and counts them on the trigger", async () => {
    const { updateNodeConfig } = renderForm({ config: { recipients: "not-a-list" } });
    expect(screen.getByText("Choose members")).toBeVisible();
    await userEvent.click(screen.getByLabelText("toggle-member-u1"));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { recipients: ["u1"] });
  });

  it("shows a field-scoped error under a collection pin", () => {
    renderForm({ errors: new Map([["collections", "Not accessible"]]) });
    expect(screen.getByText("Not accessible")).toBeVisible();
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

describe("a step's optional settings", () => {
  const needs = makeDefinition({
    id: "test.short",
    name: "Short",
    config_schema: {
      type: "object",
      required: ["message"],
      properties: {
        message: { type: "string", title: "Message" },
        tone: { type: "string", title: "Tone" },
        signature: { type: "string", title: "Signature" },
      },
    },
    input_schema: {
      type: "object",
      properties: { extra: { type: "string", title: "Extra" } },
    },
  });

  it("shows what the step needs and what is set, folding the rest under More options", () => {
    renderForm({ definition: needs, config: { signature: "Ada" }, folded: true });

    expect(screen.getByLabelText(/Message/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Signature/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Tone/)).toBeNull();
    expect(screen.queryByText("Extra")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "2 more options" }));
    expect(screen.getByLabelText(/Tone/)).toBeInTheDocument();
    expect(screen.getByText("Extra")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Fewer options" }));
    expect(screen.queryByLabelText(/Tone/)).toBeNull();
  });

  it("keeps a bound optional input in view", () => {
    renderForm({
      definition: needs,
      folded: true,
      bindings: [
        { target_node_id: "N", target_field: "extra", source: { kind: "literal", value: "x" } },
      ],
    });

    expect(screen.getByText("Extra")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 more options" })).toBeInTheDocument();
  });
});
