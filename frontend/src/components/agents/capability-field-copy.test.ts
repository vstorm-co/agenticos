import { renderHook } from "@testing-library/react";
import * as intl from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCapabilityFieldCopy } from "./capability-field-copy";

afterEach(() => vi.restoreAllMocks());

describe("useCapabilityFieldCopy", () => {
  it("names a setting for a person rather than by its code name", () => {
    const { result } = renderHook(() => useCapabilityFieldCopy("guardrails"));

    expect(result.current("redact_pii_in")).toEqual({
      title: "Hide personal data in the question",
      description: "Redact emails, phone numbers, IBANs, cards and SSNs from the prompt",
    });
  });

  it("shows a prompt field's placeholder as written, not as an ICU argument", () => {
    const { result } = renderHook(() => useCapabilityFieldCopy("compaction"));

    expect(result.current("summary_prompt")?.description).toContain("`{messages}`");
  });

  it("leaves a field the catalog does not hold to the schema", () => {
    const { result } = renderHook(() => useCapabilityFieldCopy("guardrails"));

    expect(result.current("added_after_the_catalog")).toBeNull();
  });

  it("leaves a field to the schema when the catalog holds something other than text", () => {
    const translator = { has: () => true, raw: () => ({ nested: "object" }) };
    vi.spyOn(intl, "useTranslations").mockReturnValue(
      translator as unknown as ReturnType<typeof intl.useTranslations>,
    );
    const { result } = renderHook(() => useCapabilityFieldCopy("guardrails"));

    expect(result.current("redact_pii_in")).toBeNull();
  });
});

it("localizes short environment names separately from their selected help", () => {
  const { result } = renderHook(() => useCapabilityFieldCopy("computer_use"));
  expect(result.current("desktop")?.options?.e2b?.label).toBe("E2B");
  expect(result.current("desktop")?.options?.local?.label).toBe("Local");
  expect(result.current("desktop")?.options?.sandbox?.description).toContain("Sandbox connection");
});
it.each([
  null,
  [],
  "invalid",
  {
    bad: {},
    other: { label: 4, description: "bad" },
    valid: { label: "Local", description: "Use this computer" },
  },
])("narrows optional choice translations before displaying them: %j", (raw) => {
  const original = renderHook(() => intl.useTranslations("capabilityConfig")).result.current;
  const translator = Object.assign(original, {
    has: () => true,
    raw: (key: string): unknown =>
      key.endsWith(".title")
        ? "Environment"
        : key.endsWith(".description")
          ? "Choose an environment"
          : raw,
  });
  vi.spyOn(intl, "useTranslations").mockReturnValue(translator);
  const { result } = renderHook(() => useCapabilityFieldCopy("computer_use"));
  expect(result.current("desktop")?.title).toBe("Environment");
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    expect(result.current("desktop")?.options).toEqual({
      valid: { label: "Local", description: "Use this computer" },
    });
  } else expect(result.current("desktop")?.options).toBeUndefined();
});
