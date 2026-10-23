import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import en from "../../../messages/en.json";
import type { ProposalCheckRecord } from "@/types/eval-runs";
import { sideName } from "./names";

const evals = createTranslator({ locale: "en", messages: en, namespace: "evals" });
const t = (key: string, values?: { version?: number; count?: number }) =>
  evals(key as Parameters<typeof evals>[0], values);

function check(overrides: Partial<ProposalCheckRecord> = {}): ProposalCheckRecord {
  return { kind: "agent", base_version: 2, on_draft: false, suggestions: 1, ...overrides };
}

const candidate = { role: "candidate" as const, source: "explicit" as const, version_number: null };
const baseline = { role: "baseline" as const, source: "version" as const, version_number: 2 };

describe("sideName", () => {
  it("names a check's candidate by what it adds to the side it is measured against", () => {
    expect(sideName(candidate, t, check())).toBe("v2 + 1 suggestion");
    expect(sideName(candidate, t, check({ suggestions: 3 }))).toBe("v2 + 3 suggestions");
    expect(sideName(candidate, t, check({ on_draft: true, suggestions: 2 }))).toBe(
      "Draft + 2 suggestions",
    );
    expect(sideName(candidate, t, check({ on_draft: true, base_version: null }))).toBe(
      "Draft + 1 suggestion",
    );
    expect(sideName(candidate, t, check({ kind: "skill", base_version: 4 }))).toBe(
      "v4 + proposed skill",
    );
    expect(sideName(candidate, t, check({ kind: "context", base_version: 4 }))).toBe(
      "v4 + proposed context file",
    );
  });

  it("names a baseline, and any side of another run, by what it ran", () => {
    expect(sideName(baseline, t, check())).toBe("v2");
    expect(sideName({ ...baseline, source: "draft", version_number: null }, t, check())).toBe(
      "Draft",
    );
    expect(sideName(candidate, t)).toBe("Proposed changes");
  });
});
