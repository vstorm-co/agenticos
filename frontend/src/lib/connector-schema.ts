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
 * `SchemaForm` reads for a field's label and its guidance.
 *
 * The default is the field this treats with care. A connector's `default` is a
 * placeholder, not an authoritative value: an S3 `region` left blank resolves
 * to the credential's region or `S3_RAG_REGION` server-side, never to the
 * schema's `us-east-1`, so rendering it as the field's value would show a
 * setting the sync does not use. It therefore lands on `x-placeholder` (a grey
 * hint, never stored) for the text-like kinds. A boolean is the exception: its
 * default *is* what the backend applies when the key is omitted
 * (`config.get("include_subfolders", True)`), so it stays on `default`, where
 * `SchemaForm` reflects it on the switch.
 */
function fieldToProperty(field: ConnectorConfigField): JsonSchemaProperty {
  const base: JsonSchemaProperty = { title: field.label, description: field.help };
  const placeholder = field.default == null ? undefined : String(field.default);
  switch (field.type) {
    case "integer":
      return { ...base, type: "integer", "x-placeholder": placeholder };
    case "boolean":
      return { ...base, type: "boolean", default: field.default };
    case "textarea":
      return { ...base, type: "string", "x-textarea": true, "x-placeholder": placeholder };
    case "string":
      return { ...base, type: "string", "x-placeholder": placeholder };
  }
}
