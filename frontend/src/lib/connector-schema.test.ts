import { describe, expect, it } from "vitest";

import { connectorConfigToJsonSchema } from "./connector-schema";
import type { ConnectorConfigField } from "@/lib/rag-api";

/** The shape a connector's `config_schema` arrives in, one entry per field. */
function field(overrides: Partial<ConnectorConfigField> = {}): ConnectorConfigField {
  return { type: "string", label: "Field", required: false, ...overrides };
}

describe("connectorConfigToJsonSchema", () => {
  it("carries the label as the title and the help as the description", () => {
    // SchemaForm reads `title` for the label and `description` for the guidance
    // under a field, so the connector's own words have to land on those keys.
    const schema = connectorConfigToJsonSchema({
      folder_id: field({ label: "Google Drive Folder ID", help: "The ID from the folder URL" }),
    });

    expect(schema.properties?.folder_id).toMatchObject({
      type: "string",
      title: "Google Drive Folder ID",
      description: "The ID from the folder URL",
    });
  });

  it("maps each connector field type to the control SchemaForm draws for it", () => {
    const schema = connectorConfigToJsonSchema({
      host: field({ type: "string" }),
      port: field({ type: "integer" }),
      recursive: field({ type: "boolean" }),
      manifest: field({ type: "textarea" }),
    });

    expect(schema.properties?.host?.type).toBe("string");
    expect(schema.properties?.port?.type).toBe("integer");
    expect(schema.properties?.recursive?.type).toBe("boolean");
    // A textarea is a plain multi-line string, marked so SchemaForm draws a raw
    // textarea rather than the Markdown editor a prompt gets.
    expect(schema.properties?.manifest).toMatchObject({ type: "string", "x-textarea": true });
    expect(schema.properties?.host?.["x-textarea"]).toBeUndefined();
  });

  it("collects only the required fields into the schema's required list", () => {
    const schema = connectorConfigToJsonSchema({
      bucket: field({ required: true }),
      prefix: field({ required: false }),
      region: field(),
    });

    expect(schema.required).toEqual(["bucket"]);
  });

  it("renders a text field's default as a placeholder, not a stored value", () => {
    // A connector default is a hint: an S3 region left blank resolves to the
    // credential's region server-side, never to the schema's `us-east-1`, so it
    // must not arrive as the field's value.
    const schema = connectorConfigToJsonSchema({
      region: field({ default: "us-east-1" }),
      endpoint_url: field({ default: null }),
    });

    expect(schema.properties?.region?.["x-placeholder"]).toBe("us-east-1");
    expect(schema.properties?.region?.default).toBeUndefined();
    // No default declared: no placeholder invented.
    expect(schema.properties?.endpoint_url?.["x-placeholder"]).toBeUndefined();
  });

  it("keeps a boolean's default, which the backend applies when the key is omitted", () => {
    // Unlike a text default, `config.get("include_subfolders", True)` means the
    // switch's default is what actually happens - so it stays on `default`, which
    // SchemaForm reflects on the switch.
    const schema = connectorConfigToJsonSchema({
      include_subfolders: field({ type: "boolean", default: true }),
    });

    expect(schema.properties?.include_subfolders?.default).toBe(true);
    expect(schema.properties?.include_subfolders?.["x-placeholder"]).toBeUndefined();
  });

  it("is an object schema even when the connector declares no fields", () => {
    expect(connectorConfigToJsonSchema({})).toEqual({
      type: "object",
      properties: {},
      required: [],
    });
  });
});
