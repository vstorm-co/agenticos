import { describe, expect, it } from "vitest";

import type { SkillAgentUsage } from "@/types/skill-versions";
import { isShown, lineOf, shownAgents } from "./skill-lines";

const pinned = {
  draft_only: false,
  binding: { state: "pinned", fork: null },
} as unknown as SkillAgentUsage;

describe("skill lines", () => {
  it("reads `?show=` as a state or a fork, and anything else as everyone", () => {
    expect(shownAgents("pinned")).toBe("pinned");
    expect(shownAgents("fork:f1")).toBe("fork:f1");
    expect(shownAgents("fork:")).toBe("all");
    expect(shownAgents("whatever")).toBe("all");
    expect(shownAgents(null)).toBe("all");
  });

  it("names the line a choice edits", () => {
    expect(lineOf("fork:f1")).toBe("f1");
    expect(lineOf("pinned")).toBeNull();
  });

  it("keeps an agent bound only in its draft off every line", () => {
    expect(isShown({ ...pinned, draft_only: true }, "pinned")).toBe(false);
    expect(isShown({ ...pinned, draft_only: true }, "all")).toBe(true);
    expect(isShown(pinned, "pinned")).toBe(true);
    expect(isShown(pinned, "fork:f1")).toBe(false);
  });
});
