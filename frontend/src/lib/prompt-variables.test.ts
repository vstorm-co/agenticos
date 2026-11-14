import { describe, expect, it } from "vitest";
import { promptVariablePieces, rehypePromptVariables } from "./prompt-variables";

describe("prompt variable highlighting", () => {
  it("preserves prose and leaves invalid or incomplete placeholders literal", () => {
    expect(promptVariablePieces("Hello {{user.name}}! {{not closed")).toEqual([
      { text: "Hello ", variable: false },
      { text: "{{user.name}}", variable: true },
      { text: "! {{not closed", variable: false },
    ]);
    expect(promptVariablePieces("")).toEqual([]);
  });
  it("preserves non-text syntax nodes and never changes code blocks", () => {
    const comment = { type: "comment" };
    const code = {
      type: "element",
      tagName: "code",
      properties: {},
      children: [{ type: "text", value: "{{literal}}" }],
    };
    const tree = { children: [comment, code, { type: "text", value: "{{variable}}" }] };
    rehypePromptVariables()(tree);
    expect(tree.children[0]).toBe(comment);
    expect(code.children).toEqual([{ type: "text", value: "{{literal}}" }]);
    expect(tree.children[2]).toMatchObject({ type: "element", tagName: "mark" });
  });
});
