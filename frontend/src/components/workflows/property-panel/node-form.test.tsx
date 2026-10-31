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
vi.mock("@/components/workflows/agent-step/agent-source-field", () => ({
  AgentSourceField: ({
    config,
    stepName,
    error,
    onChange,
  }: {
    config: Record<string, unknown>;
    stepName: string;
    error?: string;
    onChange: (next: Record<string, unknown>) => void;
  }) => (
    <div>
      <span>{`agent-source:${stepName}:${JSON.stringify(config)}:${error ?? ""}`}</span>
      <button
        type="button"
        aria-label="go-inline"
        onClick={() => onChange({ inline: { name: "x" } })}
      />
    </div>
  ),
}));

const mcpTool = vi.hoisted(() => ({ schema: null as Record<string, unknown> | null }));

vi.mock("@/components/workflows/pickers/mcp-tool-picker", () => ({
  useMcpToolSchema: () => mcpTool.schema,
  McpToolField: ({
    connectionId,
    tool,
    toolError,
    onChange,
  }: {
    connectionId: string | null;
    tool: string | null;
    toolError?: string;
    onChange: (next: { connectionId: string | null; tool: string | null }) => void;
  }) => (
    <div>
      <span>{`mcp-tool:${connectionId}:${tool}:${toolError ?? ""}`}</span>
      <button
        type="button"
        aria-label="pick-tool"
        onClick={() => onChange({ connectionId: "c1", tool: "find" })}
      />
      <button
        type="button"
        aria-label="clear-server"
        onClick={() => onChange({ connectionId: null, tool: null })}
      />
    </div>
  ),
  McpConnectionPicker: ({ onChange }: { onChange: (next: string | null) => void }) => (
    <div>
      <button type="button" aria-label="pick-server" onClick={() => onChange("c2")} />
      <button type="button" aria-label="unpick-server" onClick={() => onChange(null)} />
    </div>
  ),
}));

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

vi.mock("@/components/workflows/property-panel/curl-import", () => ({
  CurlImport: () => <button type="button">Import cURL</button>,
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
  useWorkflowTable: () => ({
    table: {
      columns: [
        {
          id: "name-col",
          label: "Full name",
          type: "text",
          archived: false,
          nullable: true,
          default: null,
        },
        { id: "computed", label: "Computed", type: "formula", archived: false },
      ],
    },
  }),
  useKnowledgeBases: () => ({ kbs: [] }),
  useMembers: () => ({ members: [] }),
  useModelProviders: () => ({ profiles: [], profilesStatus: "loaded" }),
}));
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({
    value,
    onChange,
  }: {
    value: string | null;
    onChange: (id: string | null) => void;
  }) => (
    <div>
      <span>{`model:${value}`}</span>
      <button type="button" onClick={() => onChange("m1")}>
        pick-model
      </button>
      <button type="button" onClick={() => onChange(null)}>
        clear-model
      </button>
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
  it("lists the list a step works on first, then its settings, then what else it reads", () => {
    const filter = makeDefinition({
      id: "data.filter",
      config_schema: {
        type: "object",
        properties: { match_mode: { type: "string", title: "Match Mode" } },
        required: ["match_mode"],
      } as Schema,
      input_schema: {
        type: "object",
        properties: { label: { type: "string" }, items: { type: "array", items: {} } },
        required: ["label", "items"],
      } as Schema,
    });
    renderForm({ definition: filter });

    const labels = Array.from(document.querySelectorAll("label")).map((label) =>
      label.textContent?.replaceAll("*", "").trim(),
    );
    expect(labels.filter((text) => ["Items", "Match mode", "Label"].includes(text ?? ""))).toEqual([
      "Items",
      "Match mode",
      "Label",
    ]);
    expect(screen.queryByText("Settings")).toBeNull();
  });

  it("builds a condition from rows where the step evaluates one", async () => {
    const filter = makeDefinition({
      id: "data.filter",
      config_schema: {
        type: "object",
        properties: {
          condition: { type: "string", title: "Condition", "x-condition": "item" },
        },
        required: ["condition"],
      } as Schema,
    });
    const { updateNodeConfig } = renderForm({ definition: filter });
    expect(screen.getByRole("button", { name: "Add a condition" })).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Field of condition 1"), "ok");
    await userEvent.click(screen.getByRole("combobox", { name: "Check of condition 1" }));
    await userEvent.click(screen.getByRole("option", { name: "is not empty" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { condition: "item.ok" });
  });

  it("draws a merge's own panel in place of its raw config", () => {
    renderForm({
      definition: makeDefinition({ id: "logic.merge", kind: "control" }),
    });
    expect(screen.getByLabelText("The branch that ran")).toBeChecked();
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

  it("draws an agent step's agent as one field, whichever half is set", async () => {
    const agentRun = makeDefinition({
      id: "agent.run",
      name: "Agent",
      config_schema: {
        type: "object",
        properties: {
          agent: { "x-resource": "agent" },
          inline: { "x-agent-spec": true },
          max_cost_usd: { type: "number" },
        },
      } as Schema,
    });
    const { updateNodeConfig } = renderForm({
      definition: agentRun,
      config: { inline: { name: "Scorer" } },
      errors: new Map([["inline", "No model selected"]]),
      folded: true,
    });

    expect(
      screen.getByText('agent-source:Agent:{"inline":{"name":"Scorer"}}:No model selected'),
    ).toBeVisible();
    // `inline` is the same field, never a second control or a folded option.
    expect(screen.getByRole("button", { name: "1 more option" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "go-inline" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { inline: { name: "x" } });
  });

  it("draws an MCP step's server and tool as one field, writing both", async () => {
    const mcpCall = makeDefinition({
      id: "mcp.call",
      config_schema: {
        type: "object",
        properties: {
          connection_id: { "x-resource": "mcp_connection" },
          tool: { type: "string" },
          timeout_seconds: { type: "integer", default: 60 },
        },
        required: ["connection_id", "tool"],
      } as Schema,
    });
    const { updateNodeConfig } = renderForm({
      definition: mcpCall,
      config: { connection_id: "c0", tool: "old", timeout_seconds: 5 },
      errors: new Map([["tool", "Not offered"]]),
    });

    expect(screen.getByText("mcp-tool:c0:old:Not offered")).toBeVisible();
    // The tool is the server field's, never a text box of its own.
    expect(screen.queryByRole("textbox", { name: /tool/i })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "pick-tool" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {
      connection_id: "c1",
      tool: "find",
      timeout_seconds: 5,
    });
    await userEvent.click(screen.getByRole("button", { name: "clear-server" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { timeout_seconds: 5 });
  });

  it("edits an MCP tool's arguments as one field each, bound by key", async () => {
    const mcpCall = makeDefinition({
      id: "mcp.call",
      config_schema: {
        type: "object",
        properties: { connection_id: { "x-resource": "mcp_connection" }, tool: { type: "string" } },
      } as Schema,
      input_schema: {
        type: "object",
        properties: { arguments: { anyOf: [{ type: "object" }, { type: "null" }] } },
      } as Schema,
    });
    mcpTool.schema = {
      type: "object",
      properties: {
        email: { type: "string", description: "Whose lead" },
        limit: { type: "integer" },
      },
      required: ["email"],
    };
    const { upsertBinding } = renderForm({
      definition: mcpCall,
      config: { connection_id: "c1", tool: "find_lead" },
      folded: true,
    });

    // Shown at once, not folded: they are what the tool is called with.
    const email = screen.getByRole("textbox", { name: /email/i });
    await userEvent.type(email, "a");
    expect(upsertBinding).toHaveBeenLastCalledWith(
      expect.objectContaining({ target_field: "arguments/email" }),
    );
    expect(screen.getByText("Whose lead")).toBeInTheDocument();
    mcpTool.schema = null;
  });

  it("keeps the arguments one object while the tool's schema is unknown", () => {
    const mcpCall = makeDefinition({
      id: "mcp.call",
      config_schema: {
        type: "object",
        properties: { connection_id: { "x-resource": "mcp_connection" }, tool: { type: "string" } },
      } as Schema,
      input_schema: {
        type: "object",
        properties: { arguments: { anyOf: [{ type: "object" }, { type: "null" }] } },
      } as Schema,
    });
    mcpTool.schema = { type: "object" };
    renderForm({
      definition: mcpCall,
      config: { connection_id: "c1", tool: "find_lead" },
      folded: true,
    });

    expect(screen.queryByRole("textbox", { name: /email/i })).toBeNull();
    expect(screen.getByRole("button", { name: "1 more option" })).toBeVisible();
    mcpTool.schema = null;
  });

  it("pins an MCP server anywhere else through the server picker", async () => {
    const other = makeDefinition({
      id: "other.step",
      config_schema: {
        type: "object",
        properties: { server: { "x-resource": "mcp_connection", title: "Server" } },
        required: ["server"],
      } as Schema,
    });
    const { updateNodeConfig } = renderForm({ definition: other, config: { server: "c1" } });

    await userEvent.click(screen.getByRole("button", { name: "pick-server" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { server: "c2" });
    await userEvent.click(screen.getByRole("button", { name: "unpick-server" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("picks a model step's model from the organization's models", async () => {
    const prompt = makeDefinition({
      id: "ai.prompt",
      config_schema: {
        type: "object",
        properties: {
          model_profile_id: { "x-resource": "model_profile", title: "Model" },
        },
        required: ["model_profile_id"],
      } as Schema,
    });
    const { updateNodeConfig } = renderForm({
      definition: prompt,
      config: { model_profile_id: "m0" },
    });

    expect(screen.getByText("Model")).toBeVisible();
    expect(screen.getByText("model:m0")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "pick-model" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { model_profile_id: "m1" });
    await userEvent.click(screen.getByRole("button", { name: "clear-model" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("asks an extraction step for its fields, with no answer in prose to choose", () => {
    const extract = makeDefinition({
      id: "ai.extract",
      config_schema: {
        type: "object",
        properties: { output_schema: { type: "object", title: "Fields to extract" } },
        required: ["output_schema"],
      } as Schema,
    });
    renderForm({ definition: extract });

    expect(screen.queryByText("As the agent answers")).toBeNull();
    expect(screen.queryByRole("combobox", { name: "It answers" })).toBeNull();
  });

  it("offers a prompt step an answer in prose by default", () => {
    const prompt = makeDefinition({
      id: "ai.prompt",
      config_schema: {
        type: "object",
        properties: { structured_output_schema: { type: "object" } },
      } as Schema,
    });
    renderForm({ definition: prompt });

    expect(screen.queryByText("As the agent answers")).toBeNull();
    expect(screen.getByRole("combobox", { name: "It answers" })).toHaveTextContent("In text");
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
    expect(screen.queryByText("Settings")).toBeNull();
  });

  it.each([
    ["trigger.manual", /Start it with Run/],
    ["core.input", /POST \/api\/v1\/workflow-runs/],
  ])("gives %s its typed input fields, under how it starts", (id, hint) => {
    renderForm({ definition: makeDefinition({ id, category: "triggers" }) });
    expect(screen.getByText(hint)).toBeVisible();
    expect(screen.getByRole("button", { name: "Add field" })).toBeVisible();
    expect(screen.queryByText("Settings")).toBeNull();
  });

  it("gives a form its page's words above the fields it asks for", () => {
    renderForm({ definition: makeDefinition({ id: "trigger.form", category: "triggers" }) });
    expect(screen.getByText(/gives this workflow a public page/)).toBeVisible();
    expect(screen.getByLabelText("Title")).toBeVisible();
    expect(screen.getByLabelText("After sending")).toBeVisible();
    expect(screen.getByRole("button", { name: "Add field" })).toBeVisible();
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

describe("a code field", () => {
  const code = makeDefinition({
    id: "test.code",
    config_schema: {
      type: "object",
      properties: {
        code: {
          type: "string",
          title: "Code",
          "x-code": "python",
          "x-placeholder": "sum(args['x'])",
          description: "Read the bound values as args.",
        },
      },
      required: ["code"],
    },
    input_schema: null,
  });

  it("is edited in the code editor, with its help and its error", async () => {
    const { updateNodeConfig } = renderForm({
      definition: code,
      config: { code: "x" },
      errors: new Map([["code", "Not valid Python"]]),
    });
    const editor = screen.getByRole("textbox", { name: "Code" });
    expect(editor).toHaveAttribute("placeholder", "sum(args['x'])");
    expect(screen.getByText("Read the bound values as args.")).toBeVisible();
    expect(screen.getByText("Not valid Python")).toBeVisible();

    await userEvent.type(editor, "1");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { code: "x1" });
    await userEvent.clear(editor);
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
  });

  it("starts empty when nothing is written yet", () => {
    renderForm({ definition: code });
    expect(screen.getByRole("textbox", { name: "Code" })).toHaveValue("");
  });
});

describe("an HTTP request", () => {
  it("offers to import a cURL command, and no other step does", () => {
    renderForm({
      definition: makeDefinition({ id: "http.request", config_schema: CONFIG_SCHEMA }),
    });
    expect(screen.getByRole("button", { name: "Import cURL" })).toBeVisible();
  });

  it("is not offered on another step", () => {
    renderForm();
    expect(screen.queryByRole("button", { name: "Import cURL" })).toBeNull();
  });
});

describe("names mapped to text", () => {
  const headers = makeDefinition({
    id: "test.headers",
    config_schema: {
      type: "object",
      properties: {
        headers: {
          type: "object",
          title: "Headers",
          additionalProperties: { type: "string" },
        },
      },
    },
    input_schema: null,
  });

  it("shows each entry as a row, and saves what is typed", async () => {
    const { updateNodeConfig } = renderForm({
      definition: headers,
      config: { headers: { "X-Lead": "yes" } },
    });
    expect(screen.getByLabelText("Name 1")).toHaveValue("X-Lead");
    expect(screen.getByLabelText("Value 1")).toHaveValue("yes");

    await userEvent.type(screen.getByLabelText("Value 1"), "!");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { headers: { "X-Lead": "yes!" } });
  });

  it("adds a row that is saved once it has a name, and removes one", async () => {
    const { updateNodeConfig } = renderForm({ definition: headers });
    await userEvent.click(screen.getByRole("button", { name: "Add row" }));
    await userEvent.type(screen.getByLabelText("Value 1"), "v");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
    await userEvent.type(screen.getByLabelText("Name 1"), "X");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", { headers: { X: "v" } });

    await userEvent.click(screen.getByRole("button", { name: "Remove row 1" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {});
    expect(screen.queryByLabelText("Name 1")).toBeNull();
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

  it("brings the folded options out just above its button, and keeps them there while filled", () => {
    const shown = () =>
      Array.from(document.querySelectorAll("[data-field]")).map((field) =>
        field.getAttribute("data-field"),
      );
    const props = (config: Record<string, unknown>) => {
      const instance = node("N", needs.id, config);
      return {
        definition: needs,
        node: instance,
        graph: graph({ entry: "N", nodes: [instance], bindings: [] }),
        catalog: makeCatalog([needs]),
        bindings: [],
        errors: new Map<string, string>(),
        updateNodeConfig: vi.fn(),
        upsertBinding: vi.fn(),
        removeBinding: vi.fn(),
      };
    };
    const { rerender } = render(<NodeForm {...props({ signature: "Ada" })} />);
    fireEvent.click(screen.getByRole("button", { name: "2 more options" }));
    // Not in their usual places up the form, where a click below would not see them.
    expect(shown()).toEqual(["message", "signature", "tone", "extra"]);

    // Given a value, Tone stays where it came out rather than jumping up the form.
    rerender(<NodeForm {...props({ signature: "Ada", tone: "warm" })} />);
    expect(shown()).toEqual(["message", "signature", "tone", "extra"]);

    // Folded again, what is set takes its usual place, and the rest goes.
    fireEvent.click(screen.getByRole("button", { name: "Fewer options" }));
    expect(shown()).toEqual(["message", "tone", "signature"]);
  });

  it("keeps a field it showed in place while open, after it is cleared or unbound", () => {
    const shown = () =>
      Array.from(document.querySelectorAll("[data-field]")).map((field) =>
        field.getAttribute("data-field"),
      );
    const extra: Binding = {
      target_node_id: "N",
      target_field: "extra",
      source: { kind: "literal", value: "x" },
    };
    const props = (config: Record<string, unknown>, bindings: Binding[]) => {
      const instance = node("N", needs.id, config);
      return {
        definition: needs,
        node: instance,
        graph: graph({ entry: "N", nodes: [instance], bindings }),
        catalog: makeCatalog([needs]),
        bindings,
        errors: new Map<string, string>(),
        updateNodeConfig: vi.fn(),
        upsertBinding: vi.fn(),
        removeBinding: vi.fn(),
      };
    };
    const { rerender } = render(<NodeForm {...props({ signature: "Ada" }, [extra])} />);
    fireEvent.click(screen.getByRole("button", { name: "1 more option" }));
    expect(shown()).toEqual(["message", "signature", "extra", "tone"]);

    // Cleared and unbound under the cursor, neither leaves while the options are open.
    rerender(<NodeForm {...props({}, [])} />);
    expect(shown()).toEqual(["message", "signature", "extra", "tone"]);

    // Folded again, they fold by the usual rule.
    fireEvent.click(screen.getByRole("button", { name: "Fewer options" }));
    expect(shown()).toEqual(["message"]);
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

describe("an approval step's choices", () => {
  const approval = makeDefinition({
    id: "human.approval",
    name: "Ask for approval",
    config_schema: {
      type: "object",
      properties: {
        title: { type: "string", title: "Title", minLength: 1 },
        choices: {
          type: "array",
          title: "Ways to approve",
          maxItems: 5,
          items: { $ref: "#/$defs/ApprovalChoice" },
        },
      },
      required: ["title"],
      $defs: {
        ApprovalChoice: {
          type: "object",
          title: "ApprovalChoice",
          properties: {
            id: { type: "string", title: "Port id", pattern: "^[a-z][a-z0-9_]{0,31}$" },
            label: { type: "string", title: "Button label", maxLength: 40 },
          },
          required: ["id", "label"],
        },
      },
    },
  });

  it("edits each choice's id and label as a row", async () => {
    const { updateNodeConfig } = renderForm({
      definition: approval,
      config: { title: "Send?", choices: [{ id: "draft", label: "Keep a draft" }] },
    });
    expect(screen.getByLabelText(/Port id/)).toHaveValue("draft");
    await userEvent.type(screen.getByLabelText(/Button label/), "!");
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {
      title: "Send?",
      choices: [{ id: "draft", label: "Keep a draft!" }],
    });
    await userEvent.click(screen.getByRole("button", { name: "Add row" }));
    expect(updateNodeConfig).toHaveBeenLastCalledWith("N", {
      title: "Send?",
      choices: [{ id: "draft", label: "Keep a draft" }, {}],
    });
  });
});

it("shows writable table columns as immediate record value fields", async () => {
  renderForm({
    folded: true,
    config: { table: { table_id: "table-id", schema_version: 1, column_ids: null } },
    definition: makeDefinition({
      id: "table.record.create",
      input_schema: {
        type: "object",
        properties: { values: { type: "object", title: "Values", additionalProperties: {} } },
      },
    }),
  });
  expect(screen.getByText("Full name")).toBeVisible();
  expect(screen.queryByText("Computed")).toBeNull();
});

describe("a step's primary controls", () => {
  it("shows the HTTP method, authentication and body before opening advanced options", () => {
    renderForm({
      folded: true,
      definition: makeDefinition({
        id: "http.request",
        config_schema: {
          type: "object",
          properties: {
            method: { type: "string", enum: ["GET", "POST"], title: "Method", default: "GET" },
            auth: { type: "string", title: "Authentication" },
            timeout_seconds: { type: "integer", title: "Timeout" },
          },
        },
        input_schema: {
          type: "object",
          properties: { body: { type: "string", title: "Request body" } },
        },
      }),
    });
    expect(screen.getByLabelText("Method")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Authentication" })).toBeInTheDocument();
    expect(screen.getByText("Request body")).toBeInTheDocument();
    expect(screen.queryByLabelText("Timeout")).toBeNull();
  });

  it.each([
    ["text", "Text"],
    ["json", "JSON value"],
    ["csv", "Rows"],
  ])("shows the %s file's payload without hiding it under more options", (format, payload) => {
    renderForm({
      folded: true,
      config: { format },
      definition: makeDefinition({
        id: "file.write",
        config_schema: {
          type: "object",
          properties: {
            format: { type: "string", enum: ["text", "json", "csv"], title: "Format" },
          },
        },
        input_schema: {
          type: "object",
          properties: {
            text: { type: "string", title: "Text" },
            json_value: { type: "string", title: "JSON value" },
            rows: { type: "string", title: "Rows" },
          },
        },
      }),
    });
    expect(screen.getByLabelText("Format")).toBeInTheDocument();
    expect(screen.getByText(payload)).toBeInTheDocument();
  });
});
