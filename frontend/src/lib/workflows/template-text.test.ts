import { describe, expect, it } from "vitest";

import { parseTemplate, placeholderText, previewTemplate, templateText } from "./template-text";
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
