import { describe, expect, it } from "vitest";

import { TABLE_WRITE_PYDANTIC_SCHEMA } from "./fixtures";
import { adaptPydanticSchema, scalarUiSchema, type PydanticSchema } from "./pydantic-schema";

describe("Pydantic JSON Schema -> SDK node schema", () => {
  const adapted = adaptPydanticSchema(TABLE_WRITE_PYDANTIC_SCHEMA);
  const { properties } = adapted.schema;

  it("resolves a $ref to an enum into a Select's options", () => {
    expect(properties.mode).toMatchObject({
      type: "string",
      options: [
        { label: "insert", value: "insert" },
        { label: "upsert", value: "upsert" },
        { label: "update", value: "update" },
      ],
    });
  });

  it("unwraps Optional (anyOf with null) to the one real type", () => {
    expect(properties.key_column).toMatchObject({ type: "string", label: "Key column" });
  });

  it("turns an integer with bounds into a number with bounds", () => {
    expect(properties.batch_size).toMatchObject({ type: "number", minimum: 1, maximum: 1000 });
  });

  it("turns a list of models into an array of objects", () => {
    expect(properties.mappings).toMatchObject({
      type: "array",
      items: {
        type: "object",
        properties: { column: { type: "string" }, value: { type: "string" } },
      },
    });
  });

  it("carries required and defaults, and adds the two properties every SDK node has", () => {
    expect(adapted.schema.required).toEqual(["table_id", "mappings"]);
    expect(adapted.defaults).toEqual({ mode: "upsert", key_column: null, batch_size: 100 });
    expect(properties.label).toEqual({ type: "string" });
    expect(properties.description).toEqual({ type: "string" });
  });

  it("reports what it had to drop instead of dropping it silently", () => {
    expect(adapted.unsupported).toEqual([
      "on_conflict: a dict (additionalProperties) has no SDK equivalent",
      "tags: the SDK only accepts arrays of objects",
    ]);
    expect(properties).not.toHaveProperty("on_conflict");
    expect(properties).not.toHaveProperty("tags");
  });

  it("handles strings with bounds, booleans, nested objects and the constructs it cannot take", () => {
    const schema: PydanticSchema = {
      type: "object",
      properties: {
        name: { type: "string", minLength: 1, maxLength: 9, pattern: "^a" },
        flag: { type: "boolean" },
        inner: { type: "object", required: ["x"], properties: { x: { type: "number" } } },
        either: { anyOf: [{ type: "string" }, { type: "integer" }] },
        blob: { type: ["string", "null"] },
        nested: { $ref: "#/$defs/Inner", title: "Own title" },
      },
      $defs: { Inner: { type: "object", properties: { y: { type: "string" } } } },
    };
    const result = adaptPydanticSchema(schema);
    expect(result.schema.properties.name).toEqual({
      type: "string",
      label: "name",
      minLength: 1,
      maxLength: 9,
      pattern: "^a",
    });
    expect(result.schema.properties.flag).toEqual({ type: "boolean", label: "flag" });
    expect(result.schema.properties.inner).toMatchObject({ type: "object", required: ["x"] });
    expect(result.schema.properties.nested).toMatchObject({ label: "Own title", type: "object" });
    expect(result.unsupported).toEqual([
      "either: anyOf with several non-null branches",
      'blob: unsupported type ["string","null"]',
    ]);
    expect(result.schema.required).toBeUndefined();
  });

  it("throws on a $ref it cannot resolve rather than guessing", () => {
    expect(() =>
      adaptPydanticSchema({ type: "object", properties: { a: { $ref: "#/$defs/Nope" } } }),
    ).toThrow(/unresolved \$ref/);
  });

  it("builds a form over the scalar properties only", () => {
    const ui = scalarUiSchema(adapted.schema) as unknown as {
      elements: { type: string; scope: string }[];
    };
    expect(ui.elements.map((e) => [e.type, e.scope])).toEqual([
      ["Text", "#/properties/table_id"],
      ["Select", "#/properties/mode"],
      ["Text", "#/properties/key_column"],
      ["Text", "#/properties/batch_size"],
    ]);
    const withSwitch = scalarUiSchema({
      properties: {
        label: { type: "string" },
        description: { type: "string" },
        on: { type: "boolean" },
      },
    }) as unknown as { elements: { type: string }[] };
    expect(withSwitch.elements.map((e) => e.type)).toEqual(["Switch"]);
  });
});
