import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProposedChanges } from "./proposed-changes";
import type { SkillChangeRecord } from "@/lib/skill-changes-api";

const state = vi.hoisted(() => ({
  changes: [] as SkillChangeRecord[],
  error: null as string | null,
  apply: vi.fn(),
  discard: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  useSkillChanges: () => ({
    changes: state.changes,
    isLoading: false,
    error: state.error,
    apply: state.apply,
    discard: state.discard,
    isDeciding: false,
  }),
}));

function change(overrides: Partial<SkillChangeRecord> = {}): SkillChangeRecord {
  return {
    id: "p-1",
    skill_id: "s-1",
    agent_id: "a-1",
    conversation_id: "c-1",
    name: "refunds",
    description: "How refunds work now.",
    content: "Ask for the receipt before anything else.",
    resources: {},
    status: "pending",
    decided_by_user_id: null,
    decided_at: null,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  state.changes = [change()];
  state.error = null;
});

describe("ProposedChanges", () => {
  it("says nothing at all to somebody who may not decide", () => {
    // Every route behind this is gated on skills:edit, so a panel of buttons
    // that answer 403 is worse than no panel.
    const { container } = render(<ProposedChanges canEdit={false} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("is absent when nothing is waiting", () => {
    // Which is the normal state. A permanent empty box above the skills list
    // would be a permanent reminder of a rarely used feature.
    state.changes = [];
    const { container } = render(<ProposedChanges canEdit />);

    expect(container).toBeEmptyDOMElement();
  });

  it("says why the list is empty when the request failed", () => {
    // An empty list and a failed request are otherwise the same pixels.
    state.changes = [];
    state.error = "403 Forbidden";
    render(<ProposedChanges canEdit />);

    expect(screen.getByText("403 Forbidden")).toBeVisible();
  });

  it("names the skill and whether this creates one or edits one", () => {
    // The difference decides what accepting does, and it is not recoverable
    // from the body.
    state.changes = [change(), change({ id: "p-2", skill_id: null, name: "escalation" })];
    render(<ProposedChanges canEdit />);

    expect(screen.getByText("refunds")).toBeVisible();
    expect(screen.getByText("Edit")).toBeVisible();
    expect(screen.getByText("New skill")).toBeVisible();
    expect(screen.getByText(/2 changes are waiting/)).toBeVisible();
  });

  it("counts one change in the singular", () => {
    render(<ProposedChanges canEdit />);

    expect(screen.getByText(/1 change is waiting/)).toBeVisible();
  });

  it("keeps the body behind a click, and shows it on one", async () => {
    // Six waiting need to be six rows; the body is what the decision is about.
    render(<ProposedChanges canEdit />);

    expect(screen.queryByText(/Ask for the receipt/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Show what changed in refunds/ }));

    expect(screen.getByText(/Ask for the receipt/)).toBeVisible();
  });

  it("lists the files a change brings with it", async () => {
    // A skill whose script did not come with it is a skill that stopped working.
    state.changes = [change({ resources: { "reconcile.py": "print(1)" } })];
    render(<ProposedChanges canEdit />);

    await userEvent.click(screen.getByRole("button", { name: /Show what changed in refunds/ }));

    expect(screen.getByText("reconcile.py")).toBeVisible();
  });

  it("hides the body again on a second click", async () => {
    render(<ProposedChanges canEdit />);
    const toggle = screen.getByRole("button", { name: /Show what changed in refunds/ });

    await userEvent.click(toggle);
    await userEvent.click(toggle);

    expect(screen.queryByText(/Ask for the receipt/)).toBeNull();
  });

  it("points at the conversation the change came from", () => {
    // Most of what makes the decision possible: the same edit means different
    // things asked by a lead and inferred from one complaint.
    render(<ProposedChanges canEdit />);

    expect(screen.getByRole("link", { name: /Read the conversation/ })).toHaveAttribute(
      "href",
      "/chat?c=c-1",
    );
  });

  it("offers no conversation link for a change that has none", () => {
    state.changes = [change({ conversation_id: null })];
    render(<ProposedChanges canEdit />);

    expect(screen.queryByRole("link", { name: /Read the conversation/ })).toBeNull();
  });

  it("prompts for a description the agent left empty", () => {
    // It is what every other agent reads before loading the skill at all.
    state.changes = [change({ description: "" })];
    render(<ProposedChanges canEdit />);

    expect(screen.getByText(/worth adding one before accepting/)).toBeVisible();
  });

  it("accepts and refuses through their own actions", async () => {
    render(<ProposedChanges canEdit />);

    await userEvent.click(screen.getByRole("button", { name: /Apply the change to refunds/ }));
    expect(state.apply).toHaveBeenCalledWith("p-1");

    await userEvent.click(screen.getByRole("button", { name: /Discard the change to refunds/ }));
    expect(state.discard).toHaveBeenCalledWith("p-1");
  });
});
