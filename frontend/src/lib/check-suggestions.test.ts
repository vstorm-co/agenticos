import { describe, expect, it } from "vitest";

import { BULLET_PATTERN, escapePattern, suggestCheck } from "./check-suggestions";

const read = (description: string, name = "") => suggestCheck({ name, description });

describe("suggestCheck", () => {
  it.each([
    ["The answer is at most 50 words.", { unit: "words", max: 50 }],
    ["No more than 120 characters.", { unit: "characters", max: 120 }],
    ["Keeps it under 1,000 chars", { unit: "characters", max: 1000 }],
    ["Max 3 words", { unit: "words", max: 3 }],
    ["Maximum of 1 word", { unit: "words", max: 1 }],
    ["Up to 80 characters long", { unit: "characters", max: 80 }],
    ["40 words or fewer", { unit: "words", max: 40 }],
    ["At least 20 words", { unit: "words", min: 20 }],
    ["Is no shorter than 300 characters", { unit: "characters", min: 300 }],
    ["200 characters or more", { unit: "characters", min: 200 }],
    ["Between 20 and 60 words", { unit: "words", min: 20, max: 60 }],
    ["between 60 to 20 WORDS", { unit: "words", min: 20, max: 60 }],
    ["At least 10 words and at most 40 words", { unit: "words", min: 10, max: 40 }],
  ])("reads a length from %j", (description, bounds) => {
    expect(read(description)).toEqual({ kind: "length", check: { type: "length", ...bounds } });
  });

  it("keeps the most when the least is in another unit or above it", () => {
    expect(read("At least 10 characters and at most 40 words")?.check).toEqual({
      type: "length",
      unit: "words",
      max: 40,
    });
    expect(read("At least 90 words and at most 40 words")?.check).toEqual({
      type: "length",
      unit: "words",
      max: 40,
    });
  });

  it("reads the criterion's name as well as its description", () => {
    expect(read("Short and to the point", "At most 30 words")?.kind).toBe("length");
  });

  it("checks an opening it is quoted, and escapes it", () => {
    expect(read('Starts with "Dear customer"')).toEqual({
      kind: "startsWith",
      text: "Dear customer",
      check: { type: "regex", value: "^Dear customer" },
    });
    expect(read("Begins with the phrase “Hi (there).”")?.check).toEqual({
      type: "regex",
      value: "^Hi \\(there\\)\\.",
    });
    expect(read("Starts with a greeting")).toBeNull();
    expect(read('Starts with " "')).toBeNull();
  });

  it.each(["Uses a bulleted list", "Answers in bullet points", "Lists the steps as bullets"])(
    "checks a bulleted list in %j",
    (description) => {
      expect(read(description)).toEqual({
        kind: "bullets",
        check: { type: "regex", value: BULLET_PATTERN },
      });
    },
  );

  it("checks that a JSON answer is an object, and not one that must not be JSON", () => {
    expect(read("Returns valid JSON")).toEqual({
      kind: "json",
      check: { type: "json_schema", schema: { type: "object" } },
    });
    expect(read("Does not wrap the answer in JSON")).toBeNull();
  });

  it("suggests nothing for a criterion only a judge can grade", () => {
    expect(read("Polite, and names the refund policy")).toBeNull();
    expect(read("")).toBeNull();
  });
});

describe("escapePattern", () => {
  it("escapes every character a pattern treats specially", () => {
    expect(escapePattern("a.b*c+d?e^f$g{h}i(j)k|l[m]n\\o")).toBe(
      "a\\.b\\*c\\+d\\?e\\^f\\$g\\{h\\}i\\(j\\)k\\|l\\[m\\]n\\\\o",
    );
  });
});
