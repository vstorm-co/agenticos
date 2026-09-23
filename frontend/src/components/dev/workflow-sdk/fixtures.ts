import type { PydanticSchema } from "./pydantic-schema";
import type { WorkflowGraph } from "./typed-graph";

/**
 * MOCK. What the backend's `TableWriteConfig.model_json_schema()` would return
 * once virtual tables exist (#1783). Hand-written, in the shape Pydantic v2
 * emits: `$defs`, `$ref`, `anyOf [X, null]`, `enum` on a `StrEnum`, an `int`
 * with bounds, and a `dict[str, str]` the SDK cannot represent.
 */
export const TABLE_WRITE_PYDANTIC_SCHEMA: PydanticSchema = {
  $defs: {
    ColumnMapping: {
      title: "ColumnMapping",
      type: "object",
      properties: {
        column: { title: "Column", type: "string" },
        value: { title: "Value", type: "string", description: "A literal or a {{ binding }}." },
      },
      required: ["column", "value"],
    },
    WriteMode: { title: "WriteMode", type: "string", enum: ["insert", "upsert", "update"] },
  },
  title: "TableWriteConfig",
  type: "object",
  properties: {
    table_id: { title: "Table", type: "string" },
    mode: { $ref: "#/$defs/WriteMode", default: "upsert" },
    key_column: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      title: "Key column",
    },
    batch_size: { title: "Batch size", type: "integer", default: 100, minimum: 1, maximum: 1000 },
    mappings: { title: "Mappings", type: "array", items: { $ref: "#/$defs/ColumnMapping" } },
    on_conflict: {
      title: "On conflict",
      type: "object",
      additionalProperties: { type: "string" },
    },
    tags: { title: "Tags", type: "array", items: { type: "string" } },
  },
  required: ["table_id", "mappings"],
};

/** MOCK. The virtual tables an org would own; `GET /tables` does not exist yet. */
export const MOCK_TABLES: readonly { id: string; name: string; columns: readonly string[] }[] = [
  { id: "tbl-invoices", name: "Invoices", columns: ["invoice_no", "vendor", "amount", "status"] },
  { id: "tbl-contacts", name: "Contacts", columns: ["email", "name", "company"] },
];

/** Two ids per level make copy/paste remapping visible in the fixture. */
export function sampleGraph(): WorkflowGraph {
  return {
    nodes: [
      { id: "start", label: "Start", position: { x: 0, y: 120 }, config: { kind: "start" } },
      {
        id: "each-file",
        label: "For each file",
        position: { x: 280, y: 120 },
        config: {
          kind: "foreach",
          items: "{{ start.files }}",
          concurrency: 2,
          body: {
            nodes: [
              {
                id: "extract",
                label: "Extract fields",
                position: { x: 0, y: 60 },
                config: {
                  kind: "agent",
                  agent_id: "",
                  version_id: "",
                  prompt: "Read {{ each-file.item }}",
                },
              },
              {
                id: "each-line",
                label: "For each line",
                position: { x: 280, y: 60 },
                config: {
                  kind: "foreach",
                  items: "{{ extract.lines }}",
                  concurrency: 1,
                  body: {
                    nodes: [
                      {
                        id: "write-line",
                        label: "Write line",
                        position: { x: 0, y: 0 },
                        config: {
                          kind: "table_write",
                          table_id: "tbl-invoices",
                          mode: "upsert",
                          key_column: "invoice_no",
                          batch_size: 100,
                          mappings: [{ column: "amount", value: "{{ each-line.item.amount }}" }],
                          on_conflict: { amount: "keep_new" },
                        },
                      },
                    ],
                    edges: [],
                  },
                },
              },
            ],
            edges: [{ id: "e-x-l", source: "extract", target: "each-line" }],
          },
        },
      },
      { id: "end", label: "End", position: { x: 560, y: 120 }, config: { kind: "end" } },
    ],
    edges: [
      { id: "e-1", source: "start", target: "each-file" },
      { id: "e-2", source: "each-file", target: "end" },
    ],
  };
}

/** A second, visibly different document, so a save under the wrong key shows. */
export function secondGraph(): WorkflowGraph {
  return {
    nodes: [
      { id: "b-start", label: "B start", position: { x: 0, y: 0 }, config: { kind: "start" } },
      { id: "b-end", label: "B end", position: { x: 300, y: 0 }, config: { kind: "end" } },
    ],
    edges: [{ id: "b-e1", source: "b-start", target: "b-end" }],
  };
}
