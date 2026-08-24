/**
 * A RAG connector's `config_schema`, in the shape `SchemaForm` renders.
 *
 * There are two schema contracts on this platform for "a form the backend
 * describes": capabilities and secret kinds publish JSON Schema straight from
 * Pydantic, while a connector publishes the bespoke `ConnectorConfigField`
 * mapping in `app/schemas/sync_source.py`. `SchemaForm` renders the first, and
 * this is the one place that turns the second into it - so the sync-source
 * wizard draws its config step with the same component the Builder and the vault
 * use, rather than a second renderer maintained in parallel (#568).
 *
 * This function is the whole of the field-type alignment: a fifth
 * `ConnectorFieldType` cannot be added without the `switch` below ceasing to
 * return for it, which is a compile error until a mapping is chosen here. The
 * bridge exists because the two backend shapes have not yet converged; #1093
 * removes both it and `ConnectorConfigField`.
 */

import type { ConnectorConfigField } from "@/lib/rag-api";
import type { JsonSchema, JsonSchemaProperty } from "@/types/agents";

/** Convert a connector's `config_schema` into the JSON Schema `SchemaForm` reads. */
export function connectorConfigToJsonSchema(
  configSchema: Record<string, ConnectorConfigField>,
): JsonSchema {
  const properties: Record<string, JsonSchemaProperty> = {};
  const required: string[] = [];
  for (const [name, field] of Object.entries(configSchema)) {
    properties[name] = fieldToProperty(field);
    if (field.required) required.push(name);
  }
  return { type: "object", properties, required };
}

/**
 * One connector field as a JSON Schema property.
 *
 * `label` becomes `title` and `help` becomes `description`, which is what
 * `SchemaForm` reads for a field's label and its guidance. `default` is passed
 * through untouched: the backend serialises an absent default as `null`, and
 * `SchemaForm`'s own `defaultOf` already reads that as "no default".
 */
function fieldToProperty(field: ConnectorConfigField): JsonSchemaProperty {
  const base: JsonSchemaProperty = {
    title: field.label,
    description: field.help,
    default: field.default,
  };
  switch (field.type) {
    case "integer":
      return { ...base, type: "integer" };
    case "boolean":
      return { ...base, type: "boolean" };
    case "textarea":
      return { ...base, type: "string", "x-textarea": true };
    case "string":
      return { ...base, type: "string" };
  }
}
