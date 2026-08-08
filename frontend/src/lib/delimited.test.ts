import { describe, expect, it } from "vitest";

import { parseDelimited } from "./delimited";

/**
 * The reason there is a parser here at all rather than a `split(",")`.
 *
 * Every case below is one an agent's own `report.csv` hits: a quoted field with a
 * comma in it, a quote inside that, a cell holding two lines, and a file written on
 * Windows.
 */
describe("reading a delimited file", () => {
  it("reads plain rows", () => {
    expect(parseDelimited("name,total\nAcme,42")).toEqual([
      ["name", "total"],
      ["Acme", "42"],
    ]);
  });

  it("reads a quoted field containing the delimiter", () => {
    expect(parseDelimited('name,note\n"Acme, Inc.",fine')).toEqual([
      ["name", "note"],
      ["Acme, Inc.", "fine"],
    ]);
  });

  it("reads an escaped quote inside a quoted field", () => {
    expect(parseDelimited('note\n"He said ""no"""')).toEqual([["note"], ['He said "no"']]);
  });

  it("reads a newline inside a quoted field as part of it", () => {
    expect(parseDelimited('note\n"line one\nline two"')).toEqual([
      ["note"],
      ["line one\nline two"],
    ]);
  });

  it("reads tabs as a delimiter too", () => {
    expect(parseDelimited("name\ttotal\nAcme\t42")).toEqual([
      ["name", "total"],
      ["Acme", "42"],
    ]);
  });

  it("reads Windows line endings", () => {
    expect(parseDelimited("name,total\r\nAcme,42\r\n")).toEqual([
      ["name", "total"],
      ["Acme", "42"],
    ]);
  });

  it("reads a bare carriage return as a line ending", () => {
    expect(parseDelimited("a\rb")).toEqual([["a"], ["b"]]);
  });

  it("ends the last row even without a trailing newline", () => {
    expect(parseDelimited("a,b")).toEqual([["a", "b"]]);
  });

  it("keeps an empty trailing cell, which is a value", () => {
    expect(parseDelimited("a,b\n1,")).toEqual([
      ["a", "b"],
      ["1", ""],
    ]);
  });

  it("has no rows for an empty file", () => {
    expect(parseDelimited("")).toEqual([]);
  });
});
