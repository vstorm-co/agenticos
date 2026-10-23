import { describe, expect, it } from "vitest";

import {
  consolePath,
  inputProblems,
  progress,
  rejection,
  resolveAction,
  sameRun,
  showValue,
  startedRun,
} from "./artifact-actions";
import type { ActionFieldType, ArtifactActionField, ArtifactActionView } from "@/types/artifact";

function field(
  type: ActionFieldType,
  over: Partial<ArtifactActionField> = {},
): ArtifactActionField {
  return { name: "f", label: null, type, required: false, description: null, options: [], ...over };
}

function action(workflow_id: string, name: string, label: string): ArtifactActionView {
  return { workflow_id, name, label, fields: [] };
}

describe("resolveAction", () => {
  const a = action("11111111-aaaa", "Send report", "Mail it");
  const b = action("22222222-bbbb", "Mail it", "Tidy");

  it("matches the id exactly: no trimming, no case folding", () => {
    expect(resolveAction([a], " 11111111-aaaa")).toBeNull();
    expect(resolveAction([a], "11111111-AAAA")).toBeNull();
    expect(resolveAction([a], "11111111-aaaa")).toBe(a);
  });

  it("prefers the workflow id, so a label can never shadow it", () => {
    const shadow = action("33333333-cccc", "Other", "11111111-AAAA");
    expect(resolveAction([a, shadow], "11111111-aaaa")).toBe(a);
  });

  it("takes the label before the name", () => {
    expect(resolveAction([a, b], " mail IT ")).toBe(a);
    expect(resolveAction([a, b], "tidy")).toBe(b);
    expect(resolveAction([a, b], "send report")).toBe(a);
  });

  it("matches nothing when a tier is ambiguous, and does not fall through", () => {
    const twin = action("44444444-dddd", "Another", "Mail it");
    expect(resolveAction([a, twin, b], "mail it")).toBeNull();
  });

  it("matches nothing it was not given", () => {
    expect(resolveAction([a], "Delete")).toBeNull();
    expect(resolveAction([], "Send report")).toBeNull();
  });
});

describe("inputProblems", () => {
  const kinds = (fields: ArtifactActionField[], input: Record<string, unknown>) =>
    inputProblems(fields, input).map((problem) => problem.kind);

  it("accepts what fits", () => {
    expect(kinds([field("text", { required: true })], { f: "x" })).toEqual([]);
    expect(kinds([field("number")], { f: 1.5 })).toEqual([]);
    expect(kinds([field("integer")], { f: 2 })).toEqual([]);
    expect(kinds([field("boolean")], { f: false })).toEqual([]);
    expect(kinds([field("date")], { f: "2026-10-23" })).toEqual([]);
    expect(kinds([field("choice", { options: ["a", "b"] })], { f: "b" })).toEqual([]);
    expect(kinds([field("text")], {})).toEqual([]);
    expect(kinds([field("text")], { f: null })).toEqual([]);
  });

  it("asks for what is required, in the order the fields are declared", () => {
    const fields = [
      field("text", { name: "a", required: true }),
      field("text", { name: "b", required: true }),
    ];
    expect(inputProblems(fields, { b: "" })).toEqual([
      { field: "a", kind: "required" },
      { field: "b", kind: "required" },
    ]);
    expect(kinds([field("boolean", { required: true })], { f: null })).toEqual(["required"]);
  });

  it("names the type a value does not fit", () => {
    expect(kinds([field("text")], { f: 1 })).toEqual(["text"]);
    expect(kinds([field("number")], { f: "1" })).toEqual(["number"]);
    expect(kinds([field("number")], { f: Infinity })).toEqual(["number"]);
    expect(kinds([field("integer")], { f: 1.5 })).toEqual(["integer"]);
    expect(kinds([field("boolean")], { f: "true" })).toEqual(["boolean"]);
    expect(kinds([field("date")], { f: "23/10/2026" })).toEqual(["date"]);
    expect(kinds([field("date")], { f: "2026-13-45" })).toEqual(["date"]);
    expect(kinds([field("date")], { f: 5 })).toEqual(["date"]);
    expect(kinds([field("choice", { options: ["a"] })], { f: "z" })).toEqual(["choice"]);
    expect(kinds([field("choice", { options: ["a"] })], { f: 1 })).toEqual(["choice"]);
  });

  it("refuses a value the workflow never declared, however it is named", () => {
    expect(inputProblems([field("text")], { f: "x", other: 1 })).toEqual([
      { field: "other", kind: "unknown" },
    ]);
    expect(inputProblems([], JSON.parse('{"__proto__": 1}'))).toEqual([
      { field: "__proto__", kind: "unknown" },
    ]);
  });

  it("does not read a field off the prototype", () => {
    expect(kinds([field("text", { name: "toString", required: true })], {})).toEqual(["required"]);
  });
});

describe("showValue", () => {
  it("shows text as it is and anything else as JSON, in full", () => {
    expect(showValue("<b>x</b>")).toBe("<b>x</b>");
    expect(showValue(3)).toBe("3");
    expect(showValue({ a: [1, "b"] })).toBe('{"a":[1,"b"]}');
    expect(showValue(undefined)).toBe("undefined");
  });

  it("writes out what draws nothing or reorders text, but keeps newlines and tabs", () => {
    expect(showValue("a\u202Eb")).toBe("a\\u{202E}b");
    expect(showValue("x\u200B\u200Dy\u0007")).toBe("x\\u{200B}\\u{200D}y\\u{7}");
    expect(showValue("line\n\tnext")).toBe("line\n\tnext");
    expect(showValue({ k: "\u202E" })).toBe('{"k":"\\u{202E}"}');
  });
});

describe("what is posted to the page", () => {
  const run = {
    status: "completed",
    finished: true,
    paused: false,
    run_path: null,
    output_text: "ok",
    output_structured: { a: 1 },
    error_message: null,
  };

  it("says what did not fit on a rejection that carries problems", () => {
    expect(rejection("n1", "r1", "invalid_input", [{ field: "to", kind: "required" }])).toEqual({
      type: "agenticos:run-event",
      n: "n1",
      id: "r1",
      event: "rejected",
      reason: "invalid_input",
      problems: [{ field: "to", kind: "required" }],
    });
  });

  it("rejects with a short code under the page's own id and nonce", () => {
    expect(rejection("n1", "r1", "busy")).toEqual({
      type: "agenticos:run-event",
      n: "n1",
      id: "r1",
      event: "rejected",
      reason: "busy",
    });
  });

  it("carries a run's state, and a started one has nothing to read yet", () => {
    expect(progress("n1", "r1", run)).toEqual({
      type: "agenticos:run-event",
      n: "n1",
      id: "r1",
      event: "progress",
      ...run,
    });
    expect(progress("n1", "r1", startedRun("pending"))).toMatchObject({
      status: "pending",
      finished: false,
      paused: false,
    });
  });

  it("tells one read of a run from another by what the page would see", () => {
    expect(sameRun(null, run)).toBe(false);
    expect(sameRun(run, { ...run })).toBe(true);
    expect(sameRun(run, { ...run, status: "failed" })).toBe(false);
  });
});

describe("consolePath", () => {
  it("accepts only a path to a run in this console", () => {
    expect(consolePath("/workflows/w-1/runs/r_2?org=o-1")).toBe("/workflows/w-1/runs/r_2?org=o-1");
    expect(consolePath("/workflows/w1/runs/r1")).toBe("/workflows/w1/runs/r1");
    expect(consolePath(null)).toBeNull();
    expect(consolePath("https://evil.example/workflows/w1/runs/r1")).toBeNull();
    expect(consolePath("//evil.example/workflows/w1/runs/r1")).toBeNull();
    expect(consolePath("/workflows/w1/runs/r1?next=https://evil")).toBeNull();
    expect(consolePath("javascript:alert(1)")).toBeNull();
  });
});
