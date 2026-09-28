import { NodeType, sharedProperties } from "@workflowbuilder/sdk";
import type { PaletteItem, PaletteItemOrGroup, NodeSchema, UISchema } from "@workflowbuilder/sdk";

import { MOCK_TABLES, TABLE_WRITE_PYDANTIC_SCHEMA } from "./fixtures";
import { adaptPydanticSchema } from "./pydantic-schema";

/**
 * Node definitions for the palette and the properties panel.
 *
 * Module-level and frozen: `<WorkflowBuilder.Root nodeTypes>` requires a stable
 * reference, and a definition built in render would re-register on every render.
 */

const SCHEMA_ERRORS: string[] = [];

const cast = <T>(value: unknown): T => value as T;

/** A `uischema` element whose `type` is one of the lab's custom controls. */
function control(type: string, scope: string, extra: object = {}): unknown {
  return { type, scope, ...extra };
}

const text = (name: string, label: string, extra: object = {}) =>
  control("Text", `#/properties/${name}`, { label, ...extra });

const header = [
  text("label", "Title", { placeholder: "Node title..." }),
  text("description", "Description"),
];

const emptySchema = { properties: { ...sharedProperties } } satisfies NodeSchema;

const startNode: PaletteItem = {
  label: "Start",
  description: "Where a run begins",
  type: "start",
  icon: "Lightning",
  templateType: NodeType.StartNode,
  defaultPropertiesData: { label: "Start", description: "" },
  schema: emptySchema,
  uischema: cast<UISchema>({ type: "VerticalLayout", elements: header }),
};

const endNode: PaletteItem = {
  label: "End",
  description: "Where a run finishes",
  type: "end",
  icon: "Flag",
  templateType: NodeType.Node,
  defaultPropertiesData: { label: "End", description: "" },
  schema: emptySchema,
  uischema: cast<UISchema>({ type: "VerticalLayout", elements: header }),
};

const agentSchema = {
  required: ["agent_id", "version_id"],
  properties: {
    ...sharedProperties,
    agent_id: { type: "string" },
    version_id: { type: "string" },
    prompt: { type: "string" },
  },
} satisfies NodeSchema;

const agentNode: PaletteItem = {
  label: "Agent",
  description: "Run a pinned agent version",
  type: "agent",
  icon: "AiAgent",
  templateType: NodeType.Node,
  defaultPropertiesData: {
    label: "Agent",
    description: "",
    agent_id: "",
    version_id: "",
    prompt: "",
  },
  schema: agentSchema,
  uischema: cast<UISchema>({
    type: "VerticalLayout",
    elements: [
      ...header,
      control("AgentVersion", "#/properties/agent_id"),
      control("VariableTextArea", "#/properties/prompt", {
        label: "Prompt",
        placeholder: "Use {{ to insert a variable",
        minRows: 4,
      }),
    ],
  }),
};

const adapted = adaptPydanticSchema(TABLE_WRITE_PYDANTIC_SCHEMA);
SCHEMA_ERRORS.push(...adapted.unsupported);

/** What the Pydantic schema cannot know: which tables exist. */
const tableSchema: NodeSchema = {
  ...adapted.schema,
  properties: {
    ...adapted.schema.properties,
    table_id: {
      type: "string",
      label: "Table",
      options: MOCK_TABLES.map((table) => ({ label: table.name, value: table.id })),
    },
  },
};

const tableNode: PaletteItem = {
  label: "Write to table",
  description: "Insert, update or upsert rows in a virtual table",
  type: "table_write",
  icon: "Table",
  templateType: NodeType.Node,
  defaultPropertiesData: {
    label: "Write to table",
    description: "",
    table_id: "",
    mode: "upsert",
    key_column: "",
    batch_size: 100,
    mappings: [],
    ...adapted.defaults,
  },
  schema: tableSchema,
  uischema: cast<UISchema>({
    type: "VerticalLayout",
    elements: [
      ...header,
      control("Select", "#/properties/table_id", { label: "Table" }),
      control("Select", "#/properties/mode", { label: "Mode" }),
      control("TableColumn", "#/properties/key_column", { label: "Key column" }),
      control("Text", "#/properties/batch_size", { label: "Batch size" }),
      control("ColumnMappings", "#/properties/mappings", { label: "Column mappings" }),
    ],
  }),
};

const foreachNode: PaletteItem = {
  label: "For each",
  description: "Run a body once per item",
  type: "foreach",
  icon: "Repeat",
  templateType: NodeType.Node,
  defaultPropertiesData: { label: "For each", description: "", items: "", concurrency: 1 },
  schema: {
    required: ["items"],
    properties: {
      ...sharedProperties,
      items: { type: "string" },
      concurrency: { type: "number", minimum: 1 },
    },
  },
  uischema: cast<UISchema>({
    type: "VerticalLayout",
    elements: [
      ...header,
      control("VariableText", "#/properties/items", {
        label: "Items",
        placeholder: "{{ start.files }}",
      }),
      control("Text", "#/properties/concurrency", { label: "Concurrency" }),
    ],
  }),
};

export const NODE_TYPES: PaletteItemOrGroup[] = [
  startNode,
  agentNode,
  tableNode,
  foreachNode,
  endNode,
];

/** Constructs the Pydantic schema had that the SDK could not take. */
export const DROPPED_BY_SCHEMA_ADAPTER: readonly string[] = SCHEMA_ERRORS;
