import { describe, expect, it } from "vitest";

import {
  type InputField,
  fieldCaption,
  initialValues,
  inputFieldsOf,
  payloadSchema,
  runInputFrom,
  typedPayloadPort,
} from "./input-fields";
import type { Port } from "./types";

function field(patch: Partial<InputField> = {}): InputField {
  return {
    name: "email",
    label: null,
    type: "text",
    required: true,
    description: null,
    options: [],
    ...patch,
  };
}

describe("inputFieldsOf", () => {
  it("reads the declared fields and skips entries of no known shape", () => {
    expect(inputFieldsOf({})).toEqual([]);
    expect(
      inputFieldsOf({
        fields: [
          { name: "email", type: "text" },
          { name: "plan", type: "choice", label: "Plan", required: false, options: ["a", 1] },
          { name: "odd", type: "colour" },
          { type: "text" },
          "text",
          null,
        ],
      }),
    ).toEqual([
      field(),
      field({ name: "plan", type: "choice", label: "Plan", required: false, options: ["a"] }),
    ]);
  });
});

describe("the payload a trigger with fields hands on", () => {
  it("types each field as the backend's model does, optional ones as nullable", () => {
    expect(
      payloadSchema([field(), field({ name: "seats", type: "integer", required: false })]),
    ).toEqual({
      type: "object",
      title: "Payload",
      additionalProperties: false,
      properties: {
        email: { type: "string", title: "email" },
        seats: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "seats" },
      },
      required: ["email"],
    });
  });

  it("replaces only the payload of an output port, and only when fields are declared", () => {
    const out: Port = {
      id: "out",
      label: "Out",
      kind: "output",
      schema: {
        type: "object",
        properties: { payload: { type: "object" }, triggered_by: { type: "string" } },
      },
    };
    expect(typedPayloadPort(out, [])).toBe(out);
    expect(typedPayloadPort({ ...out, schema: null }, [field()]).schema).toBeNull();
    const input: Port = { ...out, kind: "input" };
    expect(typedPayloadPort(input, [field()])).toBe(input);
    const typed = typedPayloadPort(out, [field()]).schema as {
      properties: Record<string, unknown>;
    };
    expect(typed.properties["triggered_by"]).toEqual({ type: "string" });
    expect(typed.properties["payload"]).toEqual(payloadSchema([field()]));
    expect(typedPayloadPort({ ...out, schema: { type: "object" } }, [field()]).schema).toEqual({
      type: "object",
      properties: { payload: payloadSchema([field()]) },
    });
  });
});

describe("runInputFrom", () => {
  const fields = [
    field(),
    field({ name: "n", type: "number", required: false }),
    field({ name: "i", type: "integer", required: false }),
    field({ name: "d", type: "date", required: false }),
    field({ name: "c", type: "choice", required: false, options: ["a"] }),
    field({ name: "b", type: "boolean" }),
  ];

  it("starts empty, and leaves an optional field left empty out", () => {
    expect(initialValues(fields)).toEqual({ email: "", n: "", i: "", d: "", c: "", b: false });
    expect(runInputFrom(fields, { email: " ada " })).toEqual({
      input: { email: "ada", b: false },
    });
  });

  it("types each value as declared", () => {
    expect(
      runInputFrom(fields, { email: "x", n: "1.5", i: "2", d: "2026-02-28", c: "a", b: true }),
    ).toEqual({ input: { email: "x", n: 1.5, i: 2, d: "2026-02-28", c: "a", b: true } });
  });

  it("says what is wrong with each field that cannot start the run", () => {
    expect(
      runInputFrom(fields, { email: "", n: "one", i: "1.5", d: "2026-02-30", c: "z" }),
    ).toEqual({
      problems: { email: "required", n: "number", i: "integer", d: "date", c: "choice" },
    });
    expect(runInputFrom([field({ type: "date" })], { email: "30/01/2026" })).toEqual({
      problems: { email: "date" },
    });
  });

  it("captions a field by its label, or its name", () => {
    expect(fieldCaption(field())).toBe("email");
    expect(fieldCaption(field({ label: "Email" }))).toBe("Email");
  });
});
