import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import en from "../../../messages/en.json";
import type { ProposalCheckRecord } from "@/types/eval-runs";
import { sideName } from "./names";

const evals = createTranslator({ locale: "en", messages: en, namespace: "evals" });
const t = (
  key: string,
  values?: { version?: number; count?: number; agent?: string; fork?: string },
) => evals(key as Parameters<typeof evals>[0], values);

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

  it("names a check stage's sides by the text each read", () => {
    const stage = { ...check({ kind: "skill", skill_check_id: "c-1" }) };
    expect(sideName(candidate, t, stage)).toBe("Proposed text");
    expect(sideName(baseline, t, stage)).toBe("Current text");
    expect(sideName(baseline, t, { ...stage, current: { number: 4, fork_name: null } })).toBe(
      "Current v4",
    );
    expect(sideName(baseline, t, { ...stage, current: { number: 2, fork_name: "Prints" } })).toBe(
      "Current “Prints” v2",
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

describe("sideName for a skill's check", () => {
  const skill = { ...check({ kind: "skill", base_version: 3 }), agent: "Online returns desk" };

  it("names both sides by the agent, and which skill each one read", () => {
    expect(sideName(candidate, t, skill)).toBe("Online returns desk · proposed skill");
    expect(sideName(baseline, t, skill)).toBe("Online returns desk · current skill");
  });

  it("names the stored version the proposal is weighed against, on main or a fork", () => {
    expect(sideName(baseline, t, { ...skill, current: { number: 3, fork_name: null } })).toBe(
      "Online returns desk · current skill (v3)",
    );
    expect(sideName(baseline, t, { ...skill, current: { number: 2, fork_name: "Returns" } })).toBe(
      "Online returns desk · current skill (fork “Returns” v2)",
    );
  });

  it("names them by version while the agent is unread, and a side of another run alike", () => {
    expect(sideName(candidate, t, check({ kind: "skill", base_version: 3 }))).toBe(
      "v3 + proposed skill",
    );
    expect(sideName({ source: "version", version_number: 3 }, t, skill)).toBe("v3");
  });
});
