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

  it("passes a field's default through untouched, including the absent one", () => {
    // The backend serialises a field with no default as `null`; SchemaForm's own
    // `defaultOf` reads that as "no default", so this must not rewrite it.
    const schema = connectorConfigToJsonSchema({
      region: field({ default: "us-east-1" }),
      endpoint_url: field({ default: null }),
    });

    expect(schema.properties?.region?.default).toBe("us-east-1");
    expect(schema.properties?.endpoint_url?.default).toBeNull();
  });

  it("is an object schema even when the connector declares no fields", () => {
    expect(connectorConfigToJsonSchema({})).toEqual({
      type: "object",
      properties: {},
      required: [],
    });
  });
});
