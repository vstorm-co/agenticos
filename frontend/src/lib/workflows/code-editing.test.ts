import { describe, expect, it } from "vitest";

import {
  argKeyAt,
  completeArg,
  erasePair,
  indent,
  indentUnit,
  matchingBracket,
  newline,
  typePair,
} from "./code-editing";

const at = (text: string, start: number, end = start) => ({ text, start, end });

describe("indent", () => {
  it("inserts one level at the caret: four spaces for Python, two for JavaScript", () => {
    expect(indent(at("x", 0), "python", false)).toEqual(at("    x", 4));
    expect(indent(at("x", 1), "javascript", false)).toEqual(at("x  ", 3));
    expect(indentUnit("javascript")).toBe("  ");
  });

  it("moves every selected line a level in, and out by at most a level", () => {
    const text = "a\n  b\nc";
    expect(indent(at(text, 0, text.length), "javascript", false)).toEqual({
      text: "  a\n    b\n  c",
      start: 2,
      end: text.length + 6,
    });
    const deep = "    a\n  b\nc";
    expect(indent(at(deep, 4, deep.length), "python", true)).toEqual({
      text: "a\nb\nc",
      start: 0,
      end: 5,
    });
  });

  it("outdents the caret's line without a selection", () => {
    expect(indent(at("  x", 3), "javascript", true)).toEqual(at("x", 1));
  });
});

describe("newline", () => {
  it("keeps the line's indentation", () => {
    expect(newline(at("  x = 1", 7), "python")).toEqual(at("  x = 1\n  ", 10));
  });

  it("indents a level after a block opener", () => {
    expect(newline(at("if x:", 5), "python")).toEqual(at("if x:\n    ", 10));
    expect(newline(at("if x:", 5), "javascript")).toEqual(at("if x:\n", 6));
    expect(newline(at("f(", 2), "javascript")).toEqual(at("f(\n  ", 5));
  });

  it("puts the matching closer on a line of its own", () => {
    expect(newline(at("{}", 1), "javascript")).toEqual(at("{\n  \n}", 4));
    expect(newline(at("[)", 1), "javascript")).toEqual(at("[\n  )", 4));
  });
});

describe("typePair", () => {
  it("inserts a pair, or wraps a selection", () => {
    expect(typePair(at("", 0), "(")).toEqual(at("()", 1));
    expect(typePair(at("ab", 0, 2), "[")).toEqual({ text: "[ab]", start: 1, end: 3 });
  });

  it("steps over a closer or a closing quote already there", () => {
    expect(typePair(at("()", 1), ")")).toEqual(at("()", 2));
    expect(typePair(at('""', 1), '"')).toEqual(at('""', 2));
  });

  it("types a quote plainly inside a word, and leaves other keys alone", () => {
    expect(typePair(at("don", 3), "'")).toBeNull();
    expect(typePair(at("x", 1), "a")).toBeNull();
    expect(typePair(at("x", 1), ")")).toBeNull();
  });
});

describe("erasePair", () => {
  it("takes both halves of an empty pair", () => {
    expect(erasePair(at("f()", 2))).toEqual(at("f", 1));
  });

  it("leaves anything else to the browser", () => {
    expect(erasePair(at("ab", 1))).toBeNull();
    expect(erasePair(at("()", 0))).toBeNull();
    expect(erasePair(at("(x)", 1, 2))).toBeNull();
    expect(erasePair(at("(x", 1))).toBeNull();
  });
});

describe("argKeyAt and completeArg", () => {
  it("finds a quoted key in either language, and a dotted one in JavaScript", () => {
    expect(argKeyAt(`x = args["na`, 12, "python")).toEqual({ prefix: "na", from: 10, quote: '"' });
    expect(argKeyAt("args.sc", 7, "javascript")).toEqual({ prefix: "sc", from: 5, quote: null });
    expect(argKeyAt("args.sc", 7, "python")).toBeNull();
  });

  it("completes a key and closes the quote once", () => {
    expect(completeArg(`args['na`, 8, { from: 6, quote: "'" }, "name")).toEqual(
      at("args['name']", 12),
    );
    expect(completeArg(`args['na']`, 8, { from: 6, quote: "'" }, "name")).toEqual(
      at("args['name']", 12),
    );
    expect(completeArg("args.sc", 7, { from: 5, quote: null }, "scores")).toEqual(
      at("args.scores", 11),
    );
  });
});

describe("matchingBracket", () => {
  it("pairs the bracket before the caret, or the one after it, with its match", () => {
    const text = "f(a[0], {b: (c)})";
    expect(matchingBracket(text, 2)).toEqual([1, 16]);
    expect(matchingBracket(text, 17)).toEqual([1, 16]);
    expect(matchingBracket(text, 3)).toEqual([3, 5]);
    expect(matchingBracket(text, 12)).toEqual([12, 14]);
    expect(matchingBracket(text, 16)).toEqual([8, 15]);
  });

  it("is null beside no bracket, at either end, or for one left open", () => {
    expect(matchingBracket("abc", 1)).toBeNull();
    expect(matchingBracket("", 0)).toBeNull();
    expect(matchingBracket("(()", 1)).toBeNull();
    expect(matchingBracket("())", 3)).toBeNull();
  });
});
