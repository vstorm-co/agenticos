import { describe, expect, it } from "vitest";

import type { JsonSchema } from "@/types/agents";
import { conditionalChoices, editSchemaConfig } from "./schema-config-edit";

const coding: JsonSchema = {
  type: "object",
  properties: {
    harness: { default: "claude_code" },
    runs_on: { default: "sandbox" },
    access: {
      default: "edit",
      "x-enum-when": {
        field: "harness",
        choices: { claude_code: ["read_only", "edit"], codex: ["edit"] },
        unless: { field: "runs_on", equals: ["this_computer"] },
      },
    },
    model: {
      "x-enum-when": {
        field: "harness",
        choices: { claude_code: ["anthropic:a"], codex: ["openai:b"] },
      },
      "x-visible-when": { field: "runs_on", equals: ["sandbox", "personal_sandbox"] },
    },
    base_url: { "x-visible-when": { field: "harness", equals: ["claude_code"] } },
  },
};

describe("conditional Coding Agent settings", () => {
  it("restores read-only and the model after a harness switch and an autosave", () => {
    const remembered = new Map<string, unknown>();
    const original = {
      harness: "claude_code",
      access: "read_only",
      model: "anthropic:a",
      base_url: "https://gateway.example",
    };
    const codex = editSchemaConfig(coding, original, "harness", "codex", remembered);
    const saved = JSON.parse(JSON.stringify(codex)) as Record<string, unknown>;
    expect(saved).toEqual({ harness: "codex" });

    const withModel = editSchemaConfig(coding, saved, "model", "openai:b", remembered);
    const withAccess = editSchemaConfig(coding, withModel, "access", "edit", remembered);
    const reverted = editSchemaConfig(coding, withAccess, "harness", "claude_code", remembered);
    expect(reverted).toStrictEqual(original);
    expect(editSchemaConfig(coding, reverted, "harness", "codex", remembered).model).toBe(
      "openai:b",
    );
  });

  it("does not restore an old mode's model under a different execution setting", () => {
    const remembered = new Map<string, unknown>();
    const original = { harness: "claude_code", runs_on: "sandbox", model: "anthropic:a" };
    const desktop = editSchemaConfig(coding, original, "runs_on", "this_computer", remembered);
    expect(desktop.model).toBeUndefined();
    const personal = editSchemaConfig(coding, desktop, "runs_on", "personal_sandbox", remembered);
    expect(personal.model).toBeUndefined();
    expect(editSchemaConfig(coding, personal, "runs_on", "sandbox", remembered)).toEqual(original);
  });

  it("still removes incompatible values if the caller does not remember them", () => {
    const next = editSchemaConfig(coding, { model: "anthropic:a" }, "harness", "codex");
    expect(next).toStrictEqual({ harness: "codex", model: undefined, base_url: undefined });
  });

  it("keeps the schema's original choices unless a conditional enum constrains them", () => {
    expect(conditionalChoices({}, coding, {})).toBeUndefined();
    const access = coding.properties!.access!;
    expect(conditionalChoices(access, coding, { harness: "unregistered" })).toEqual([]);
    expect(conditionalChoices(access, coding, { runs_on: "this_computer" })).toBeUndefined();
    expect(editSchemaConfig({ type: "object" }, {}, "other", true)).toEqual({ other: true });
  });
});
