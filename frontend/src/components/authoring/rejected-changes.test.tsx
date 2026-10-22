import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

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
    await userEvent.click(screen.getByText("8 proposed changes were not recorded"));

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
  });

  it("counts one in the singular, and lists all when none is cut", () => {
    render(<RejectedChanges report={report({ rejected: REJECTED.slice(0, 1) })} />);
    expect(screen.getByText("1 proposed change was not recorded")).toBeInTheDocument();
    expect(screen.queryByText(/more are not listed/)).toBeNull();
  });
});
