import { describe, expect, it } from "vitest";

import {
  completePlaceholder,
  openPlaceholderAt,
  parseTemplate,
  placeholderText,
  previewTemplate,
  templateSegments,
  templateText,
} from "./template-text";
import type { NodeOutputRef, TemplateValue } from "./types";

const names = new Map([
  ["a", "Form"],
  ["b", "Form copy"],
]);

function ref(nodeId: string, ...path: string[]): NodeOutputRef {
  return { kind: "node_output", node_id: nodeId, port: "out", field_path: path };
}

const resolve = (nodeId: string, path: string[]) =>
  path.includes("nope") ? null : ref(nodeId, ...path);

describe("a template as text", () => {
  const template: TemplateValue = {
    kind: "template",
    parts: ["Hi ", ref("a", "payload", "name"), "!"],
  };

  it("names each placeholder by its step", () => {
    expect(templateText(template, names)).toBe("Hi {{Form.payload.name}}!");
    expect(placeholderText("gone", [], names)).toBe("{{gone}}");
  });

  it("reads placeholders back, the longest step name first", () => {
    expect(parseTemplate("Hi {{ Form copy.x }} and {{Form}}", names, resolve)).toEqual({
      parts: ["Hi ", ref("b", "x"), " and ", ref("a")],
    });
    expect(parseTemplate("{{Form.a}}", names, resolve)).toEqual({ parts: [ref("a", "a")] });
    expect(parseTemplate("plain", names, resolve)).toEqual({ parts: ["plain"] });
  });

  it("names the placeholder it cannot read", () => {
    expect(parseTemplate("Hi {{Nobody.x}}", names, resolve)).toEqual({ unknown: "{{Nobody.x}}" });
    expect(parseTemplate("Hi {{Form.nope}}", names, resolve)).toEqual({ unknown: "{{Form.nope}}" });
  });
});

describe("a template's preview", () => {
  it("fills in what the last runs saw and marks what they did not", () => {
    const template: TemplateValue = {
      kind: "template",
      parts: [
        ref("a", "payload", "name"),
        " ",
        ref("a", "payload", "tags"),
        " ",
        ref("a", "x", "y"),
        ref("b"),
      ],
    };
    const stepData = {
      a: { output: { payload: { name: "Ada", tags: ["eu"] }, x: 3 }, error: null, runId: "r" },
    };

    expect(previewTemplate(template, stepData, names)).toEqual({
      text: 'Ada ["eu"] {{Form.x.y}}{{Form copy}}',
      missing: ["{{Form.x.y}}", "{{Form copy}}"],
    });
  });
});

describe("templateSegments", () => {
  it("cuts text where each placeholder starts and ends, keeping every character", () => {
    const text = "Hi {{Form.name}}, see {{ Triage the ticket }}.";
    const segments = templateSegments(text);
    expect(segments).toEqual([
      { text: "Hi ", placeholder: false },
      { text: "{{Form.name}}", placeholder: true },
      { text: ", see ", placeholder: false },
      { text: "{{ Triage the ticket }}", placeholder: true },
      { text: ".", placeholder: false },
    ]);
    expect(segments.map((segment) => segment.text).join("")).toBe(text);
  });

  it("has no placeholder in plain text, an unclosed one or an empty string", () => {
    expect(templateSegments("plain {{ open")).toEqual([
      { text: "plain {{ open", placeholder: false },
    ]);
    expect(templateSegments("")).toEqual([]);
    expect(templateSegments("{{a}}{{b}}").map((segment) => segment.placeholder)).toEqual([
      true,
      true,
    ]);
  });
});

describe("a placeholder being written", () => {
  it("is found from its {{ to the caret, with what was typed after the braces", () => {
    expect(openPlaceholderAt("Hi {{ Tri", 9)).toEqual({ start: 3, query: "Tri" });
    expect(openPlaceholderAt("{{", 2)).toEqual({ start: 0, query: "" });
  });

  it("is none once closed, across a line, before any {{, or with a brace typed in it", () => {
    expect(openPlaceholderAt("{{Form.name}} and", 17)).toBeNull();
    expect(openPlaceholderAt("{{Form\nname", 11)).toBeNull();
    expect(openPlaceholderAt("plain", 5)).toBeNull();
    expect(openPlaceholderAt("{{a{b", 5)).toBeNull();
  });

  it("is written out up to the caret, or over closing braces already there", () => {
    expect(completePlaceholder("Hi {{Tri and", 8, 3, "{{Triage.x}}")).toEqual({
      text: "Hi {{Triage.x}} and",
      caret: 15,
    });
    expect(completePlaceholder("{{Tri}} rest", 5, 0, "{{Triage.x}}")).toEqual({
      text: "{{Triage.x}} rest",
      caret: 12,
    });
  });
});
