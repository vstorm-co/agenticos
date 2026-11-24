import { describe, expect, it } from "vitest";
import { insertPromptField, promptFields } from "./routine-prompt-fields";

describe("routine payload fields", () => {
  it("keeps body-root paths, containers, arrays, unusual keys and present falsy values", () => {
    expect(
      promptFields({
        issue: { title: "A", "unusual.key": false },
        items: [{ name: 0 }],
        "top key": null,
      }),
    ).toEqual([
      { path: "issue", value: { title: "A", "unusual.key": false }, depth: 0 },
      { path: "issue.title", value: "A", depth: 1 },
      { path: 'issue["unusual.key"]', value: false, depth: 1 },
      { path: "items", value: [{ name: 0 }], depth: 0 },
      { path: "items[0]", value: { name: 0 }, depth: 1 },
      { path: "items[0].name", value: 0, depth: 2 },
      { path: '["top key"]', value: null, depth: 0 },
    ]);
  });
  it("replaces the selected range and returns the caret after the reference", () => {
    expect(insertPromptField("Triage old now", "issue.title", 7, 10)).toEqual({
      value: "Triage {{issue.title}} now",
      caret: 22,
    });
  });
});
