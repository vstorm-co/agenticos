import { describe, expect, it } from "vitest";

import { hunk } from "@/test-utils/authoring";
import type { RejectedChange } from "@/types/authoring";
import { changeGroup, editedOnAccept, grouped, ideaState, oneSentence } from "./authoring-groups";

const idea = (overrides: Partial<RejectedChange> = {}): RejectedChange => ({
  kind: "create_skill",
  reason: "insufficient_evidence",
  change: { name: "returns", content: "Ask first." },
  ...overrides,
});

describe("authoring groups", () => {
  it("puts each kind of change in its group", () => {
    expect(changeGroup("instructions")).toBe("instructions");
    expect(changeGroup("tool_override")).toBe("tools");
    expect(changeGroup("spec_field")).toBe("settings");
    expect(changeGroup("create_skill")).toBe("skills");
  });

  it("orders groups the same way whatever order the changes came in, and drops empty ones", () => {
    const groups = grouped(["skills", "instructions", "skills"] as const, (group) => group);
    expect(groups).toEqual([
      ["instructions", ["instructions"]],
      ["skills", ["skills", "skills"]],
    ]);
  });

  it("tells an accepted change that was edited from one accepted as suggested", () => {
    const text = hunk({ status: "accepted", accepted_text: "Mine." });
    expect(editedOnAccept(text)).toBe(true);
    expect(editedOnAccept({ ...text, accepted_text: text.new_text })).toBe(false);
    expect(editedOnAccept({ ...text, accepted_text: null })).toBe(false);
    expect(editedOnAccept({ ...text, status: "dismissed" })).toBe(false);
    const field = hunk({ kind: "spec_field", status: "accepted", new_value: 0.2 });
    expect(editedOnAccept({ ...field, accepted_value: 0.4 })).toBe(true);
    expect(editedOnAccept({ ...field, accepted_value: 0.2 })).toBe(false);
    expect(editedOnAccept({ ...field, accepted_value: null })).toBe(false);
    expect(editedOnAccept(hunk({ kind: "tool_override", status: "accepted" }))).toBe(false);
  });

  it("says where a new-skill idea stands, and nothing about the rest", () => {
    expect(ideaState(idea())).toBe("waiting");
    expect(ideaState(idea({ skill_id: "skill-1", dismissed: true }))).toBe("created");
    expect(ideaState(idea({ dismissed: true }))).toBe("dismissed");
    expect(ideaState(idea({ change: { name: "returns" } }))).toBeNull();
    expect(ideaState(idea({ kind: "instructions" }))).toBeNull();
  });

  it("summarises a change in its first sentence, never with a run id in it", () => {
    expect(oneSentence({ expected_effect: "Fewer wrong windows. Then more.", rationale: "" })).toBe(
      "Fewer wrong windows.",
    );
    expect(oneSentence({ expected_effect: "", rationale: "  Readers corrected it  " })).toBe(
      "Readers corrected it",
    );
    expect(oneSentence({ expected_effect: "", rationale: "Run 467abd40 said so." })).toBe("");
    expect(
      oneSentence({
        expected_effect: "",
        rationale:
          "It fails to refuse plainly (runs e38ca3e9-40c1-4289-bddc-ae56ce48422f, 3e1929d0). This fixes it.",
      }),
    ).toBe("It fails to refuse plainly.");
    expect(
      oneSentence({ expected_effect: "", rationale: "Run 467abd40 failed. Run 3e1929d0 too." }),
    ).toBe("");
    expect(
      oneSentence({ expected_effect: "", rationale: "Run 467abd40 failed. So we fix it." }),
    ).toBe("So we fix it.");
  });
});
