import { describe, expect, it } from "vitest";

import type { Schema } from "./schema-model";
import {
  asFormProperty,
  classify,
  defsOf,
  humanise,
  isBindable,
  isRecord,
  labelOf,
  objectFields,
  resolveRef,
  resourceKind,
  singleFieldSchema,
  unwrapOptional,
} from "./schema-model";

describe("isRecord", () => {
  it("accepts a plain object and rejects arrays, null and primitives", () => {
    expect(isRecord({})).toBe(true);
    expect(isRecord([])).toBe(false);
    expect(isRecord(null)).toBe(false);
    expect(isRecord("x")).toBe(false);
  });
});

describe("defsOf", () => {
  it("returns the $defs block, or an empty map when absent or malformed", () => {
    expect(defsOf({ $defs: { A: { type: "string" } } })).toEqual({ A: { type: "string" } });
    expect(defsOf({})).toEqual({});
    expect(defsOf({ $defs: "nope" })).toEqual({});
  });
});

describe("resolveRef", () => {
  const defs = { Row: { type: "object", properties: { a: { type: "string" } } } };

  it("follows a $ref to its def", () => {
    expect(resolveRef({ $ref: "#/$defs/Row" }, defs)).toBe(defs.Row);
  });

  it("returns the schema unchanged with no $ref", () => {
    const schema: Schema = { type: "string" };
    expect(resolveRef(schema, defs)).toBe(schema);
  });

  it("returns the schema unchanged when the def is missing", () => {
    const schema: Schema = { $ref: "#/$defs/Gone" };
    expect(resolveRef(schema, defs)).toBe(schema);
  });
});

describe("unwrapOptional", () => {
  it("unwraps a single non-null anyOf branch", () => {
    expect(unwrapOptional({ anyOf: [{ type: "string" }, { type: "null" }] })).toEqual({
      type: "string",
    });
  });

  it("leaves a real multi-type anyOf and a plain schema alone", () => {
    const multi: Schema = { anyOf: [{ type: "string" }, { type: "integer" }] };
    expect(unwrapOptional(multi)).toBe(multi);
    const plain: Schema = { type: "string" };
    expect(unwrapOptional(plain)).toBe(plain);
  });
});

describe("classify", () => {
  it("classifies an object as a fieldset, dropping const-only and non-record fields", () => {
    const shape = classify(
      {
        type: "object",
        properties: {
          name: { type: "string", title: "Name" },
          kind: { const: "x" },
          bogus: "nope",
        },
        required: ["name"],
      },
      {},
    );
    expect(shape.kind).toBe("object");
    if (shape.kind !== "object") return;
    expect(shape.entries).toEqual([
      { name: "name", schema: { type: "string", title: "Name" }, required: true },
    ]);
  });

  it("classifies an array of objects as repeatable, resolving the item $ref", () => {
    const defs = { Row: { type: "object", properties: { a: { type: "string" } } } };
    const shape = classify({ type: "array", items: { $ref: "#/$defs/Row" } }, defs);
    expect(shape.kind).toBe("array");
    if (shape.kind !== "array") return;
    expect(shape.items).toBe(defs.Row);
  });

  it("treats an array of scalars and an array with no items as leaves", () => {
    expect(classify({ type: "array", items: { type: "string" } }, {}).kind).toBe("leaf");
    expect(classify({ type: "array" }, {}).kind).toBe("leaf");
  });

  it("classifies a discriminated union from a shared const", () => {
    const shape = classify(
      {
        oneOf: [
          {
            type: "object",
            title: "Text",
            properties: { kind: { const: "text" }, text: { type: "string" } },
          },
          { type: "object", properties: { kind: { const: "number" }, n: { type: "integer" } } },
        ],
      },
      {},
    );
    expect(shape.kind).toBe("union");
    if (shape.kind !== "union") return;
    expect(shape.discriminator).toBe("kind");
    expect(shape.branches.map((b) => [b.value, b.label])).toEqual([
      ["text", "Text"],
      ["number", "number"],
    ]);
  });

  it("uses a declared discriminator propertyName", () => {
    const shape = classify(
      {
        discriminator: { propertyName: "type" },
        oneOf: [{ type: "object", properties: { type: { const: "a" } } }],
      },
      {},
    );
    expect(shape.kind).toBe("union");
  });

  it("is not a union when a branch lacks the discriminator const", () => {
    const shape = classify(
      {
        discriminator: { propertyName: "kind" },
        oneOf: [
          { type: "object", properties: { kind: { const: "a" } } },
          { type: "object", properties: { other: { type: "string" } } },
        ],
      },
      {},
    );
    expect(shape.kind).not.toBe("union");
  });

  it("is not a union with a non-record branch, an empty oneOf, or no shared const", () => {
    expect(classify({ oneOf: [1] } as unknown as Schema, {}).kind).toBe("leaf");
    expect(classify({ oneOf: [] }, {}).kind).toBe("leaf");
    expect(
      classify(
        {
          oneOf: [
            { type: "object", properties: { a: { const: "x" } } },
            { type: "object", properties: { b: { const: "y" } } },
          ],
        },
        {},
      ).kind,
    ).toBe("leaf");
  });

  it("is not a union when the inferred first branch has no properties", () => {
    const shape = classify(
      {
        oneOf: [{ type: "object" }, { type: "object", properties: { k: { const: "a" } } }],
      },
      {},
    );
    expect(shape.kind).toBe("leaf");
  });

  it("is not a union when a branch has no properties under a declared discriminator", () => {
    const shape = classify(
      {
        discriminator: { propertyName: "kind" },
        oneOf: [{ type: "object", properties: { kind: { const: "a" } } }, { type: "object" }],
      },
      {},
    );
    expect(shape.kind).toBe("leaf");
  });

  it("classifies a scalar as a leaf", () => {
    expect(classify({ type: "string" }, {}).kind).toBe("leaf");
  });
});

describe("objectFields", () => {
  it("returns an object's entries, or an empty list otherwise", () => {
    expect(
      objectFields({ type: "object", properties: { a: { type: "string" } } }, {}),
    ).toHaveLength(1);
    expect(objectFields({ type: "string" }, {})).toEqual([]);
  });
});

describe("resourceKind", () => {
  it("reads the x-resource keyword", () => {
    expect(resourceKind({ "x-resource": "agent" })).toBe("agent");
    expect(resourceKind({ "x-resource": "table" })).toBe("table");
    expect(resourceKind({ "x-resource": "secret" })).toBe("secret");
    expect(resourceKind({ "x-resource": "other" })).toBeNull();
    expect(resourceKind({})).toBeNull();
  });
});

describe("isBindable", () => {
  it("reads x-bindable", () => {
    expect(isBindable({ "x-bindable": true })).toBe(true);
    expect(isBindable({ "x-bindable": false })).toBe(false);
    expect(isBindable({})).toBe(false);
  });
});

describe("humanise / labelOf", () => {
  it("humanises a snake_case name and an empty string", () => {
    expect(humanise("default_top_k")).toBe("Default top k");
    expect(humanise("")).toBe("");
  });

  it("prefers a schema title over the humanised name", () => {
    expect(labelOf({ title: "Nice" }, "raw_name")).toBe("Nice");
    expect(labelOf({}, "raw_name")).toBe("Raw name");
  });
});

describe("singleFieldSchema / asFormProperty", () => {
  it("wraps a leaf as a one-field object schema, honouring required", () => {
    expect(singleFieldSchema("value", { type: "string" }, true)).toEqual({
      type: "object",
      properties: { value: { type: "string" } },
      required: ["value"],
    });
    expect(singleFieldSchema("value", { type: "string" }, false).required).toEqual([]);
  });

  it("views a catalog schema as a form property without copying it", () => {
    const schema: Schema = { type: "string" };
    expect(asFormProperty(schema)).toBe(schema);
  });
});
