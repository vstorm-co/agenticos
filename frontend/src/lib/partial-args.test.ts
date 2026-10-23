import { describe, expect, it } from "vitest";

import { partialArgs } from "./partial-args";

describe("partialArgs", () => {
  it("reads every field of a finished object", () => {
    expect(partialArgs('{"title": "Flow", "height": 480, "big": true, "n": null}')).toEqual({
      title: { value: "Flow", complete: true },
      height: { value: 480, complete: true },
      big: { value: true, complete: true },
      n: { value: null, complete: true },
    });
  });

  it("keeps the field being written, with what has arrived of it", () => {
    expect(partialArgs('{"kind": "svg", "content": "<svg viewBox')).toEqual({
      kind: { value: "svg", complete: true },
      content: { value: "<svg viewBox", complete: false },
    });
  });

  it("holds back a lone backslash until the escape arrives", () => {
    expect(partialArgs('{"content": "a\\')).toEqual({
      content: { value: "a", complete: false },
    });
  });

  it("holds back half a \\uXXXX escape rather than dropping the value", () => {
    expect(partialArgs('{"content": "ab\\u00')).toEqual({
      content: { value: "ab", complete: false },
    });
  });

  it("holds back the first half of a surrogate pair until the second arrives", () => {
    expect(partialArgs('{"content": "x\\ud83d\\ude')).toEqual({
      content: { value: "x", complete: false },
    });
    expect(partialArgs('{"content": "x\\ud83d\\ude00"}').content!.value).toBe("x😀");
  });

  it("reads a lone high surrogate followed by something else as itself", () => {
    expect(partialArgs('{"c": "\\ud83dxyzwvu"}').c!.value).toBe("\ud83dxyzwvu");
  });

  it("decodes the short escapes", () => {
    expect(partialArgs('{"c": "\\"\\\\\\/\\b\\f\\n\\r\\t\\q"}').c!.value).toBe('"\\/\b\f\n\r\tq');
  });

  it("reads nested values whole once their delimiter arrives", () => {
    expect(
      partialArgs('{"images": [{"name": "a", "s": "]"}], "edits": {"x": [1, 2]}, "z": 1}'),
    ).toEqual({
      images: { value: [{ name: "a", s: "]" }], complete: true },
      edits: { value: { x: [1, 2] }, complete: true },
      z: { value: 1, complete: true },
    });
  });

  it("reads an escaped quote inside a nested value without ending the string early", () => {
    expect(partialArgs('{"images": [{"name": "a\\"]b"}], "z": 1}')).toEqual({
      images: { value: [{ name: 'a"]b' }], complete: true },
      z: { value: 1, complete: true },
    });
  });

  it("treats a nested value that has not closed as not there yet", () => {
    expect(partialArgs('{"images": [{"name": "a"')).toEqual({});
  });

  it("reads a number that has not met its delimiter as unfinished", () => {
    expect(partialArgs('{"height": 48')).toEqual({ height: { value: 48, complete: false } });
  });

  it("gives nothing for text that is not an object, or a name still arriving", () => {
    expect(partialArgs("[1, 2]")).toEqual({});
    expect(partialArgs('{"tit')).toEqual({});
    expect(partialArgs('{"title" "x"}')).toEqual({});
    expect(partialArgs('{"title": ')).toEqual({});
    expect(partialArgs("{ 3 }")).toEqual({});
  });
});
