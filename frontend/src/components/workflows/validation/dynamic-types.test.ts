import { describe, expect, it } from "vitest";

import { ERROR_PORT } from "@/lib/workflows/ports";

import {
  edge,
  graph,
  makeDefinition,
  node,
  objectSchema,
  port,
  STRING,
  INTEGER,
  OPTIONAL_STRING,
} from "./fixtures";
import { rule8NoParallelFanout } from "./rules";
import {
  ANY_SCHEMA,
  isDynamic,
  outputFieldNames,
  resolveFieldType,
  typesCompatible,
  UNKNOWN,
} from "./schema";
import type { DefinitionMap } from "./topology";

/**
 * The type rules the backend applied in #1789 and #1790, mirrored so the editor
 * does not flag a binding publishing accepts: a path through a value with no
 * declared shape is checked when the run has it, optional models are walked
 * through, and a union fits member by member.
 */

const RECORD = objectSchema("Record", { email: STRING }, []);
const ITEM = {
  type: "object",
  title: "LoopItemOutput",
  properties: { item: { title: "Item" }, index: INTEGER },
};
const LOOKUP = {
  type: "object",
  title: "Lookup",
  properties: { record: { anyOf: [{ $ref: "#/$defs/Record" }, { type: "null" }] } },
  $defs: { Record: RECORD },
};
const PAYLOAD = { type: "object", additionalProperties: true };

const LOOP_ITEM = makeDefinition({ id: "loop.item", ports: [port("out", "output", ITEM)] });
const GET = makeDefinition({ id: "table.record.get", ports: [port("out", "output", LOOKUP)] });

describe("isDynamic", () => {
  it("reads Any and a free-form object as dynamic, optionally | None", () => {
    expect(isDynamic({ title: "Item" })).toBe(true);
    expect(isDynamic(PAYLOAD)).toBe(true);
    expect(isDynamic({ type: "object", additionalProperties: {} })).toBe(true);
    expect(isDynamic({ anyOf: [PAYLOAD, { type: "null" }] })).toBe(true);
  });

  it("reads a declared shape, a typed map and a real union as fixed", () => {
    expect(isDynamic(RECORD)).toBe(false);
    expect(isDynamic({ type: "object", additionalProperties: INTEGER })).toBe(false);
    expect(isDynamic({ anyOf: [STRING, INTEGER] })).toBe(false);
    expect(isDynamic(STRING)).toBe(false);
    expect(isDynamic(null)).toBe(false);
    expect(isDynamic(UNKNOWN)).toBe(false);
  });
});

describe("resolveFieldType", () => {
  it("resolves anything past a dynamic value to Any", () => {
    expect(resolveFieldType(LOOP_ITEM, "out", ["item", "record_id"])).toBe(ANY_SCHEMA);
  });

  it("walks through an optional model", () => {
    expect(resolveFieldType(GET, "out", ["record", "email"])).toEqual(STRING);
    expect(outputFieldNames(GET, "out", ["record"])).toEqual(["email"]);
  });
});

describe("typesCompatible", () => {
  it("leaves Any on either side to the dispatcher", () => {
    expect(typesCompatible(ANY_SCHEMA, STRING)).toBe(true);
    expect(typesCompatible(STRING, ANY_SCHEMA)).toBe(true);
  });

  it("lets a free-form field take any structured value, but not a scalar", () => {
    expect(typesCompatible(RECORD, PAYLOAD)).toBe(true);
    expect(typesCompatible(STRING, PAYLOAD)).toBe(false);
  });

  it("fits a union member by member, null set aside", () => {
    expect(typesCompatible(STRING, OPTIONAL_STRING)).toBe(true);
    expect(typesCompatible(OPTIONAL_STRING, STRING)).toBe(true);
    expect(typesCompatible({ anyOf: [STRING, INTEGER] }, STRING)).toBe(false);
  });

  it("compares control ports and unknowns by what they are", () => {
    expect(typesCompatible(null, null)).toBe(true);
    expect(typesCompatible(null, STRING)).toBe(false);
    expect(typesCompatible(UNKNOWN, STRING)).toBe(false);
  });
});

describe("rule 8 and a routed failure", () => {
  it("does not count a step's error port as a second way out", () => {
    const routed = makeDefinition({
      id: "data.map",
      ports: [port("out", "output", null), port(ERROR_PORT, "output", null)],
    });
    const g = graph({
      entry: "A",
      nodes: [node("A", "data.map"), node("B", "x"), node("C", "x")],
      edges: [edge("e1", "A", "out", "B", "in"), edge("e2", "A", ERROR_PORT, "C", "in")],
    });
    const definitions: DefinitionMap = new Map([["A", routed]]);
    expect(rule8NoParallelFanout(g, definitions)).toEqual([]);
  });
});
