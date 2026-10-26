import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AuthoringRequest, RejectedChange } from "@/types/authoring";
import { RejectedChanges } from "./rejected-changes";

const REJECTED: RejectedChange[] = [
  {
    kind: "instructions",
    reason: "ambiguous_anchor",
    change: { old_text: "within 30 days", new_text: "within 14 days", rationale: "Shorter" },
  },
  {
    kind: "instructions",
    reason: "unanchored",
    change: { old_text: "", new_text: "Sign off.", after: "Be brief." },
  },
  { kind: "instructions", reason: "no_change", change: { old_text: "", new_text: "" } },
  {
    kind: "tool_override",
    reason: "unknown_tool",
    change: { capability_id: "knowledge", tool_id: "search", name: null, description: "Look" },
  },
  {
    kind: "spec_field",
    reason: "not_a_target",
    change: { path: "capabilities/memory_files/config", op: "set", value: { a: 1 } },
  },
  { kind: "spec_field", reason: "not_grantable", change: { path: "collection_ids", op: "add" } },
  {
    kind: "finding",
    reason: "unsupported",
    change: { verdict: "supports", text: "Greeting helps", edit: "Greet the customer." },
  },
  {
    kind: "finding",
    reason: "edit_not_in_diff",
    change: { verdict: "risk", text: "It may answer in Klingon", edit: "" },
  },
  { kind: "instructions", reason: "superseded", change: { old_text: "Be brief.", new_text: "" } },
];

function report(values: Partial<NonNullable<AuthoringRequest["report"]>>) {
  return { proposed: 6, recorded: 0, ...values };
}

describe("RejectedChanges", () => {
  it("is absent when every change was recorded", () => {
    const { container, rerender } = render(<RejectedChanges report={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<RejectedChanges report={report({})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says how many were not recorded, why, and what each proposed", async () => {
    render(<RejectedChanges report={report({ rejected: REJECTED, rejected_more: 2 })} />);
    await userEvent.click(screen.getByText("11 more ideas the assistant did not add"));

    expect(screen.getByText("The passage it changes occurs more than once")).toBeVisible();
    expect(screen.getByText("within 30 days")).toBeVisible();
    expect(screen.getByText("Proposed: within 14 days")).toBeVisible();
    expect(screen.getByText("Shorter")).toBeVisible();
    expect(screen.getByText("After: Be brief.")).toBeVisible();
    expect(screen.getByText("At the end of the instructions")).toBeVisible();
    expect(screen.getByText("knowledge / search")).toBeVisible();
    expect(screen.getByText("Proposed: Look")).toBeVisible();
    expect(screen.getByText("set capabilities/memory_files/config")).toBeVisible();
    expect(screen.getByText('Proposed: {"a":1}')).toBeVisible();
    expect(screen.getByText("Proposed: null")).toBeVisible();
    expect(screen.getByText("It adds something the person who asked may not grant")).toBeVisible();
    expect(screen.getAllByText("Setting")).toHaveLength(2);
    expect(screen.getByText("2 more are not listed")).toBeVisible();
    expect(screen.getAllByText("Finding")).toHaveLength(2);
    expect(
      screen.getByText("Said the edit is supported, with no evidence that could be checked"),
    ).toBeVisible();
    expect(screen.getByText("Greeting helps")).toBeVisible();
    expect(screen.getByText("About: Greet the customer.")).toBeVisible();
    expect(screen.getByText("The line it names is not part of the edit")).toBeVisible();
    expect(screen.getByText("It may answer in Klingon")).toBeVisible();
    expect(
      screen.getByText("A request started later had already replaced the suggestions"),
    ).toBeVisible();
  });

  it("counts one in the singular, and lists all when none is cut", () => {
    render(<RejectedChanges report={report({ rejected: REJECTED.slice(0, 1) })} />);
    expect(screen.getByText("1 more idea the assistant did not add")).toBeInTheDocument();
    expect(screen.queryByText(/more are not listed/)).toBeNull();
  });

  it("asks for a decision only on a skill idea written in full and not yet created", () => {
    const idea: RejectedChange = {
      kind: "create_skill",
      reason: "insufficient_evidence",
      change: { name: "Returns", description: "Returns", content: "Ask first.", answers: 1 },
    };
    const onCreateSkill = vi.fn();
    const { rerender } = render(
      <RejectedChanges
        report={report({ rejected: [idea, REJECTED[0]!] })}
        onCreateSkill={onCreateSkill}
      />,
    );
    expect(screen.getByText("2 more ideas, 1 needs your decision")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create skill" })).toBeInTheDocument();
    rerender(
      <RejectedChanges
        report={report({ rejected: [{ ...idea, skill_id: "skill-9" }] })}
        onCreateSkill={onCreateSkill}
      />,
    );
    expect(screen.getByText("1 more idea the assistant did not add")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the skill" })).toHaveAttribute(
      "href",
      "/skills/skill-9",
    );
    rerender(
      <RejectedChanges
        report={report({ rejected: [{ ...idea, change: { name: "Returns" } }, idea] })}
        onCreateSkill={onCreateSkill}
      />,
    );
    expect(screen.getByText("2 more ideas, 1 needs your decision")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Create skill" })).toHaveLength(1);
  });
});
