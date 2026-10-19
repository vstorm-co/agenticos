import { describe, expect, it } from "vitest";

import { insertVariable, matching, openVariable, usedVariables } from "./variable-completion";

describe("openVariable", () => {
  it("finds the variable being typed at the caret", () => {
    expect(openVariable("Hi {{us", 7)).toEqual({ start: 3, query: "us", end: 7 });
    expect(openVariable("Hi {{ ", 6)).toEqual({ start: 3, query: "", end: 6 });
  });

  it("is closed outside braces, after them, and on anything not a name", () => {
    expect(openVariable("Hi there", 8)).toBeNull();
    expect(openVariable("{{user_name}} and", 17)).toBeNull();
    expect(openVariable('{{"a": 1', 8)).toBeNull();
  });
});

describe("matching", () => {
  const options = [{ name: "user_name" }, { name: "current_time" }, { name: "agent_name" }];

  it("puts names that start with the query before names that contain it", () => {
    expect(matching(options, "a").map((option) => option.name)).toEqual([
      "agent_name",
      "user_name",
    ]);
    expect(matching(options, "")).toHaveLength(3);
  });
});

describe("insertVariable", () => {
  it("replaces what was typed, swallowing closing braces already there", () => {
    expect(
      insertVariable("Hi {{us}} x", 7, { start: 3, query: "us", end: 7 }, "user_name"),
    ).toEqual({
      text: "Hi {{user_name}} x",
      caret: 16,
    });
    expect(insertVariable("Hi {{us", 7, { start: 3, query: "us", end: 7 }, "user_name")).toEqual({
      text: "Hi {{user_name}}",
      caret: 16,
    });
  });

  it("inserts at the caret when nothing is open", () => {
    expect(insertVariable("Hi  there", 3, null, "user_name")).toEqual({
      text: "Hi {{user_name}} there",
      caret: 16,
    });
  });
});

describe("usedVariables", () => {
  it("lists each name once", () => {
    expect(usedVariables("{{a}} {{ b }} {{a}} {{Bad}}")).toEqual(["a", "b"]);
  });
});
