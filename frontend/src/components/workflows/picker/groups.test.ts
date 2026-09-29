import { describe, expect, it } from "vitest";

import { makeDefinition } from "@/components/workflows/validation/fixtures";

import { MORE_SECTION, matchesSearch, pickerSections } from "./groups";

const step = (id: string, category: string, name = id) =>
  makeDefinition({ id, category, name, description: `does ${name}` });

describe("pickerSections", () => {
  it("groups steps into sections in reading order, a platform acting first", () => {
    const sections = pickerSections([
      step("slack.channels.find", "slack"),
      step("slack.message.send", "slack"),
      step("core.input", "triggers"),
      step("debug.echo", "debug"),
      step("custom.thing", "custom"),
      step("table.record.get", "tables"),
    ]);

    expect(sections.map((section) => section.id)).toEqual(["start", "data", "apps", MORE_SECTION]);
    const slack = sections.find((section) => section.id === "apps")?.groups[0];
    expect(slack?.items.map((item) => item.id)).toEqual([
      "slack.message.send",
      "slack.channels.find",
    ]);
    // A category no section names comes last, and a hidden one never shows.
    expect(sections.at(-1)?.groups.map((group) => group.category)).toEqual(["custom"]);
    expect(sections.flatMap((s) => s.groups).some((g) => g.category === "debug")).toBe(false);
  });

  it("sorts the categories no section names by their rank, then by name", () => {
    const sections = pickerSections([step("b.one", "zeta"), step("a.one", "alpha")]);
    expect(sections[0]?.groups.map((group) => group.category)).toEqual(["alpha", "zeta"]);
  });
});

describe("matchesSearch", () => {
  it("finds a step by its name, what it does or its group, ignoring case", () => {
    const send = step("slack.message.send", "slack", "Send a message");
    expect(matchesSearch(send, "", "Slack")).toBe(true);
    expect(matchesSearch(send, "SEND", "Slack")).toBe(true);
    expect(matchesSearch(send, "does send", "Slack")).toBe(true);
    expect(matchesSearch(send, "slack", "Slack")).toBe(true);
    expect(matchesSearch(send, "table", "Slack")).toBe(false);
  });
});
