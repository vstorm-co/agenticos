import { describe, expect, it } from "vitest";

import { localizeSchema, type FieldCopy } from "./localize-schema";

const copy: Record<string, FieldCopy> = {
  title: { title: "Tytuł", description: "Pytanie" },
  auth: { title: "Uwierzytelnianie" },
  auth__token: { placeholder: "np. abc", hint: "Z vaultu" },
  table__table_id: { title: "Tabela" },
};
const copyOf = (path: string) => copy[path] ?? {};

describe("localizeSchema", () => {
  it("words each field by its path, inline, through a $ref and an optional branch", () => {
    const schema = {
      type: "object",
      properties: {
        title: { type: "string", title: "Title", description: "The question" },
        auth: {
          title: "Auth",
          type: "object",
          properties: { token: { type: "string", title: "Token" } },
        },
        table: { anyOf: [{ $ref: "#/$defs/TableRef" }, { type: "null" }] },
        other: { $ref: "#/$defs/TableRef" },
        flag: true,
      },
      $defs: {
        TableRef: { type: "object", properties: { table_id: { title: "Table Id" } } },
      },
    };

    const worded = localizeSchema(schema, copyOf);

    expect(worded).toMatchObject({
      properties: {
        title: { title: "Tytuł", description: "Pytanie" },
        auth: {
          title: "Uwierzytelnianie",
          properties: {
            token: { title: "Token", "x-placeholder": "np. abc", "x-hint": "Z vaultu" },
          },
        },
        flag: true,
      },
      // Shared by `table` and `other`: worded once, by the first path to reach it.
      $defs: { TableRef: { properties: { table_id: { title: "Tabela" } } } },
    });
    // The served schema is left as it was.
    expect(schema.properties.title.title).toBe("Title");
    expect(schema.$defs.TableRef.properties.table_id.title).toBe("Table Id");
  });

  it("words each item of a list - inline, through a $ref, and in an optional list", () => {
    const itemCopy: Record<string, FieldCopy> = {
      choices__items__label: { title: "Etykieta" },
      rules__items__value: { title: "Wartość" },
      tags__items__name: { title: "Nazwa" },
    };
    const schema = {
      properties: {
        choices: {
          type: "array",
          items: { type: "object", properties: { label: { title: "Label" } } },
        },
        rules: { type: "array", items: { $ref: "#/$defs/Rule" } },
        tags: {
          anyOf: [
            { type: "array", items: { type: "object", properties: { name: { title: "Name" } } } },
            { type: "null" },
          ],
        },
      },
      $defs: { Rule: { type: "object", properties: { value: { title: "Value" } } } },
    };

    const worded = localizeSchema(schema, (path) => itemCopy[path] ?? {});

    expect(worded).toMatchObject({
      properties: {
        choices: { items: { properties: { label: { title: "Etykieta" } } } },
        tags: {
          anyOf: [{ items: { properties: { name: { title: "Nazwa" } } } }, { type: "null" }],
        },
      },
      $defs: { Rule: { properties: { value: { title: "Wartość" } } } },
    });
    expect(schema.properties.choices.items.properties.label.title).toBe("Label");
  });

  it("names a choice's values in the reader's words, keeping any it has none for", () => {
    const schema = {
      properties: {
        events: { "x-enum-labels": { created: "Added", deleted: "Deleted" } },
      },
    };
    const worded = localizeSchema(schema, (path) =>
      path === "events" ? { option: (value) => (value === "created" ? "Dodany" : undefined) } : {},
    );
    expect(worded).toMatchObject({
      properties: { events: { "x-enum-labels": { created: "Dodany", deleted: "Deleted" } } },
    });
    expect(schema.properties.events["x-enum-labels"].created).toBe("Added");
  });

  it("leaves a schema with nothing to word, or no properties, as it was", () => {
    expect(localizeSchema({ type: "string" }, copyOf)).toEqual({ type: "string" });
    expect(localizeSchema({ properties: { x: { $ref: "#/$defs/Gone" } } }, copyOf)).toEqual({
      properties: { x: { $ref: "#/$defs/Gone" } },
    });
  });
});
