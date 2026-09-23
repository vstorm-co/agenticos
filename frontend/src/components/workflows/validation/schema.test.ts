import { describe, expect, it } from "vitest";

import {
  DEBUG_ECHO,
  DEBUG_ECHO_OUTPUT,
  INTEGER,
  LETTER,
  NUMBER,
  PLAIN_OUTPUT,
  REQUIRED_INPUT,
  STRING,
  makeDefinition,
  objectSchema,
  port,
} from "./fixtures";
import {
  UNKNOWN,
  fieldType,
  portSchema,
  portShapesCompatible,
  resolveFieldType,
  schemaTypeToken,
  typesCompatible,
} from "./schema";

describe("schemaTypeToken", () => {
  it("names the not-found sentinel and a control port", () => {
    expect(schemaTypeToken(UNKNOWN)).toBe("unknown");
    expect(schemaTypeToken(null)).toBe("null");
  });

  it("takes a $ref's last segment as the model name", () => {
    expect(schemaTypeToken({ $ref: "#/$defs/AgentRunOutput" })).toBe("AgentRunOutput");
  });

  it("takes an object schema's title as its type name", () => {
    expect(schemaTypeToken(DEBUG_ECHO_OUTPUT)).toBe("DebugEchoOutput");
  });

  it("suffixes a scalar with its format so date-time is not plain string", () => {
    expect(schemaTypeToken(STRING)).toBe("string");
    expect(schemaTypeToken(INTEGER)).toBe("integer");
    expect(schemaTypeToken({ type: "string", format: "date-time" })).toBe("string:date-time");
  });

  it("falls back to a title with no type, then to unknown", () => {
    expect(schemaTypeToken({ title: "Bare" })).toBe("Bare");
    expect(schemaTypeToken({})).toBe("unknown");
  });
});

describe("portSchema", () => {
  it("finds a port by id and direction", () => {
    expect(portSchema(DEBUG_ECHO, "out", "output")).toBe(DEBUG_ECHO_OUTPUT);
  });

  it("is UNKNOWN for a port that does not exist in that direction", () => {
    expect(portSchema(DEBUG_ECHO, "out", "input")).toBe(UNKNOWN);
    expect(portSchema(DEBUG_ECHO, "missing", "output")).toBe(UNKNOWN);
  });
});

describe("portShapesCompatible", () => {
  it("refuses when either side is the not-found sentinel", () => {
    expect(portShapesCompatible(UNKNOWN, STRING)).toBe(false);
    expect(portShapesCompatible(STRING, UNKNOWN)).toBe(false);
  });

  it("treats a control port (null) as compatible with anything", () => {
    expect(portShapesCompatible(null, DEBUG_ECHO_OUTPUT)).toBe(true);
    expect(portShapesCompatible(DEBUG_ECHO_OUTPUT, null)).toBe(true);
  });

  it("compares two data ports by their property shapes", () => {
    expect(portShapesCompatible(REQUIRED_INPUT, PLAIN_OUTPUT)).toBe(true);
    expect(portShapesCompatible(DEBUG_ECHO_OUTPUT, REQUIRED_INPUT)).toBe(false);
    expect(portShapesCompatible(LETTER, NUMBER)).toBe(false);
  });

  it("reads an object with no properties as an empty shape", () => {
    const bare = { type: "object", title: "Bare" };
    expect(portShapesCompatible(bare, { type: "object", title: "AlsoBare" })).toBe(true);
  });

  it("tokens a non-object property value as unknown", () => {
    const oddLeft = { type: "object", properties: { x: "not-a-schema" } };
    const oddRight = { type: "object", properties: { x: 42 } };
    expect(portShapesCompatible(oddLeft, oddRight)).toBe(true);
  });
});

describe("resolveFieldType", () => {
  it("is UNKNOWN for a port that does not exist", () => {
    expect(resolveFieldType(DEBUG_ECHO, "missing", [])).toBe(UNKNOWN);
  });

  it("returns a control port's null for the empty path", () => {
    const controlSource = makeDefinition({
      id: "test.control_out",
      ports: [port("out", "output", null)],
    });
    expect(resolveFieldType(controlSource, "out", [])).toBeNull();
  });

  it("returns the whole port schema for the empty path", () => {
    expect(resolveFieldType(DEBUG_ECHO, "out", [])).toBe(DEBUG_ECHO_OUTPUT);
  });

  it("walks one level into a field", () => {
    expect(schemaTypeToken(resolveFieldType(DEBUG_ECHO, "out", ["echoed"]))).toBe("string");
  });

  it("is UNKNOWN stepping past a scalar or into a missing field", () => {
    expect(resolveFieldType(DEBUG_ECHO, "out", ["echoed", "x"])).toBe(UNKNOWN);
    expect(resolveFieldType(DEBUG_ECHO, "out", ["no_such_field"])).toBe(UNKNOWN);
  });

  it("resolves a nested $ref against the schema's own $defs", () => {
    const wrapper = {
      type: "object",
      title: "Wrapper",
      properties: { inner: { $ref: "#/$defs/Inner" } },
      required: ["inner"],
      $defs: { Inner: objectSchema("Inner", { leaf: INTEGER }, ["leaf"]) },
    };
    const nested = makeDefinition({ id: "test.nested", ports: [port("out", "output", wrapper)] });
    expect(schemaTypeToken(resolveFieldType(nested, "out", ["inner", "leaf"]))).toBe("integer");
  });
});

describe("fieldType", () => {
  it("reads an input_schema field", () => {
    expect(schemaTypeToken(fieldType(DEBUG_ECHO, "message"))).toBe("string");
  });

  it("falls back to a config_schema field", () => {
    const configOnly = makeDefinition({
      id: "test.config_only",
      input_schema: null,
      config_schema: REQUIRED_INPUT,
    });
    expect(schemaTypeToken(fieldType(configOnly, "value"))).toBe("string");
  });

  it("is UNKNOWN when neither schema declares the field", () => {
    expect(fieldType(DEBUG_ECHO, "nope")).toBe(UNKNOWN);
  });

  it("resolves a $ref field against its schema's $defs", () => {
    const schema = {
      type: "object",
      title: "Holder",
      properties: { ref: { $ref: "#/$defs/Inner" } },
      required: ["ref"],
      $defs: { Inner: objectSchema("Inner", { leaf: STRING }, ["leaf"]) },
    };
    const holder = makeDefinition({ id: "test.holder", input_schema: schema });
    expect(schemaTypeToken(fieldType(holder, "ref"))).toBe("Inner");
  });

  it("leaves a $ref untouched when its target is not in $defs", () => {
    const schema = {
      type: "object",
      title: "Holder",
      properties: { ref: { $ref: "#/$defs/Missing" } },
      required: ["ref"],
    };
    const holder = makeDefinition({ id: "test.holder_missing", input_schema: schema });
    expect(schemaTypeToken(fieldType(holder, "ref"))).toBe("Missing");
  });
});

describe("typesCompatible", () => {
  it("is true for equal tokens and false for different ones", () => {
    expect(typesCompatible(STRING, STRING)).toBe(true);
    expect(typesCompatible(STRING, INTEGER)).toBe(false);
  });
});
