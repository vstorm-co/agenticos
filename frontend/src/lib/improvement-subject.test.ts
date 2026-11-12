import { describe, expect, it } from "vitest";

import { improvementsRoot, mayContinue, subjectKey, subjectOf } from "./improvement-subject";

describe("improvement subject", () => {
  it("names an agent's session by the agent, as it always has", () => {
    const subject = subjectOf({ agent_id: "a1", skill_id: null });
    expect(subject).toBe("a1");
    expect(improvementsRoot(subject)).toBe("/agents/a1/improvements");
    expect(subjectKey(subject)).toBe("a1");
  });

  it("names a skill's session by the skill, apart from any agent's", () => {
    const subject = subjectOf({ agent_id: "", skill_id: "k1" });
    expect(subject).toEqual({ skillId: "k1" });
    expect(improvementsRoot(subject)).toBe("/skills/k1/improvements");
    expect(subjectKey(subject)).toBe("skill:k1");
  });

  it("reads an agent's access from can_restart, and leaves a skill's to the page", () => {
    expect(mayContinue({ skill_id: null, can_restart: false })).toBe(false);
    expect(mayContinue({ skill_id: null })).toBe(true);
    expect(mayContinue({ skill_id: "k1", can_restart: false })).toBe(true);
  });
});
