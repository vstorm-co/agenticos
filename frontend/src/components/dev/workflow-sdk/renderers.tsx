"use client";

import { rankWith, uiTypeIs, useJsonForms, withJsonFormsControlProps } from "@workflowbuilder/sdk";
import type { ControlProps, JsonFormsRendererExtension } from "@workflowbuilder/sdk";

import {
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgents, useAllAgentVersions } from "@/hooks/use-agents";

import { MOCK_TABLES } from "./fixtures";
import type { TableColumnMapping } from "./typed-graph";

/**
 * Custom property controls, drawn with AgenticOS's own primitives.
 *
 * They render inside the SDK's properties panel, so this is also the evidence for
 * "does a Radix popover, opened from inside the SDK's tree, land above the SDK's
 * overlays and pick up our tokens" - the lab shows the answer on screen.
 */

/** Radix cannot hold "" as an item value, so "no key column" is this sentinel. */
const NONE = "__none__";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs">{label}</span>
      {children}
    </div>
  );
}

function AgentVersionPicker({ data, handleChange, enabled }: ControlProps) {
  const core = useJsonForms().core;
  const versionId =
    typeof core?.data === "object" && core.data
      ? (core.data as Record<string, unknown>).version_id
      : "";
  const agentId = typeof data === "string" ? data : "";
  const agents = useAgents();
  const versions = useAllAgentVersions(agentId || null);

  return (
    <div className="flex flex-col gap-2" data-testid="agent-version-picker">
      <Field label="Agent">
        <Select
          value={agentId}
          disabled={enabled === false}
          onValueChange={(next) => {
            handleChange("agent_id", next);
            // A version belongs to one agent: keeping the old one would pin a
            // version the new agent does not have.
            handleChange("version_id", "");
          }}
        >
          <SelectTrigger aria-label="Agent">
            <SelectValue placeholder="Choose an agent" />
          </SelectTrigger>
          <SelectContent>
            {agents.agents.map((agent) => (
              <SelectItem key={agent.id} value={agent.id}>
                {agent.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label="Version">
        <Select
          value={typeof versionId === "string" ? versionId : ""}
          disabled={enabled === false || !agentId}
          onValueChange={(next) => handleChange("version_id", next)}
        >
          <SelectTrigger aria-label="Version">
            <SelectValue placeholder={versions.isLoading ? "Loading versions" : "Pin a version"} />
          </SelectTrigger>
          <SelectContent>
            {versions.versions.map((version) => (
              <SelectItem key={version.id} value={version.id}>
                {`v${version.version}${version.note ? ` - ${version.note}` : ""}`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
    </div>
  );
}

function TableColumnPicker({ data, handleChange, path, enabled, label }: ControlProps) {
  const core = useJsonForms().core;
  const tableId = (core?.data as Record<string, unknown> | undefined)?.table_id;
  const columns = MOCK_TABLES.find((table) => table.id === tableId)?.columns ?? [];
  return (
    <Field label={label}>
      <Select
        value={typeof data === "string" ? data : ""}
        disabled={enabled === false || columns.length === 0}
        onValueChange={(next) => handleChange(path, next === NONE ? "" : next)}
      >
        <SelectTrigger aria-label="Key column">
          <SelectValue placeholder="Choose a column" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>None</SelectItem>
          {columns.map((column) => (
            <SelectItem key={column} value={column}>
              {column}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}

function ColumnMappingsEditor({ data, handleChange, path, enabled, label }: ControlProps) {
  const rows: TableColumnMapping[] = Array.isArray(data) ? (data as TableColumnMapping[]) : [];
  const core = useJsonForms().core;
  const tableId = (core?.data as Record<string, unknown> | undefined)?.table_id;
  const columns = MOCK_TABLES.find((table) => table.id === tableId)?.columns ?? [];
  const write = (next: TableColumnMapping[]) => handleChange(path, next);

  return (
    <Field label={label}>
      <div className="flex flex-col gap-2" data-testid="column-mappings">
        {rows.map((row, index) => (
          <div key={index} className="flex items-center gap-2">
            <Select
              value={row.column}
              disabled={enabled === false}
              onValueChange={(column) =>
                write(rows.map((r, i) => (i === index ? { ...r, column } : r)))
              }
            >
              <SelectTrigger aria-label={`Column ${index + 1}`}>
                <SelectValue placeholder="Column" />
              </SelectTrigger>
              <SelectContent>
                {columns.map((column) => (
                  <SelectItem key={column} value={column}>
                    {column}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label={`Value ${index + 1}`}
              value={row.value}
              disabled={enabled === false}
              onChange={(event) =>
                write(rows.map((r, i) => (i === index ? { ...r, value: event.target.value } : r)))
              }
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={`Remove mapping ${index + 1}`}
              onClick={() => write(rows.filter((_, i) => i !== index))}
            >
              x
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={enabled === false}
          onClick={() => write([...rows, { column: "", value: "" }])}
        >
          Add mapping
        </Button>
      </div>
    </Field>
  );
}

/** Module-level and stable: the SDK appends whatever it is given on every Root mount. */
export const RENDERERS: JsonFormsRendererExtension[] = [
  {
    tester: rankWith(20, uiTypeIs("AgentVersion")),
    renderer: withJsonFormsControlProps(AgentVersionPicker),
  },
  {
    tester: rankWith(20, uiTypeIs("TableColumn")),
    renderer: withJsonFormsControlProps(TableColumnPicker),
  },
  {
    tester: rankWith(20, uiTypeIs("ColumnMappings")),
    renderer: withJsonFormsControlProps(ColumnMappingsEditor),
  },
];
