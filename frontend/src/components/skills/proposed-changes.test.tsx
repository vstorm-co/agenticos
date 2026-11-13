import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProposedChanges } from "./proposed-changes";
import type { SkillChangeRecord } from "@/lib/skill-changes-api";

const state = vi.hoisted(() => ({
  runsView: true,
  changes: [] as SkillChangeRecord[],
  error: null as string | null,
  apply: vi.fn(),
  discard: vi.fn(),
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.runsView }),
}));

vi.mock("./skill-check-dialog", () => ({
  SkillCheckDialog: ({
    change,
    forkId,
  }: {
    change: { proposalId: string };
    forkId: string | null;
  }) => <p>{`checking ${change.proposalId} on ${forkId ?? "main"}`}</p>,
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
    revision: 1,
    reaches: [],
    reaches_hidden: 0,
    fork_id: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  state.runsView = true;
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

  it("says an edit reaches its agents through a check, and a new skill reaches nobody", () => {
    const reached = {
      id: "a-1",
      name: "Refund desk",
      environments: ["production"],
      runs_now: [],
      runs_now_count: 0,
      at_promotion: [],
      at_promotion_count: 0,
    };
    state.changes = [
      change({ reaches: [reached] }),
      change({ id: "p-2", skill_id: null, name: "new-one" }),
    ];
    render(<ProposedChanges canEdit />);

    expect(
      screen.getByText("Goes live for Refund desk (production) once a check on them lets it."),
    ).toBeVisible();
    expect(screen.queryByText(/Goes live now/)).toBeNull();
    expect(screen.getByText(/No published agent reads it yet/)).toBeVisible();
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

  it("shows why the assistant proposed a change, what it expects and what it rests on", async () => {
    state.changes = [
      change({
        base_version: 3,
        authoring_request_id: "request-1",
        rationale: "Readers corrected the window.",
        expected_effect: "Answers say 30 days.",
        evidence: [{ run_id: "run-12345678", quote: "It is 30 days" }],
        evidence_dropped: 1,
      }),
    ];
    render(<ProposedChanges canEdit />);
    await userEvent.click(screen.getByRole("button", { name: /Show what changed in refunds/ }));
    expect(screen.getByText("Readers corrected the window.")).toBeInTheDocument();
    expect(screen.getByText("Answers say 30 days.")).toBeInTheDocument();
    expect(screen.getByText("It is 30 days")).toBeInTheDocument();
  });

  it("shows a rationale that came without evidence", async () => {
    state.changes = [change({ rationale: "Shorter is clearer." })];
    render(<ProposedChanges canEdit />);
    await userEvent.click(screen.getByRole("button", { name: /Show what changed in refunds/ }));
    expect(screen.getByText("Shorter is clearer.")).toBeInTheDocument();
  });

  it("says an assistant's change cited nothing it could check", async () => {
    state.changes = [change({ base_version: 2, authoring_request_id: "request-1" })];
    render(<ProposedChanges canEdit />);
    await userEvent.click(screen.getByRole("button", { name: /Show what changed in refunds/ }));
    expect(screen.getByText("No evidence that could be checked.")).toBeInTheDocument();
  });

  it("shows no evidence for a change an agent's workspace wrote", async () => {
    state.changes = [change({ base_version: 4, authoring_request_id: null })];
    render(<ProposedChanges canEdit />);
    await userEvent.click(screen.getByRole("button", { name: /Show what changed in refunds/ }));
    expect(screen.queryByText("No evidence that could be checked.")).toBeNull();
  });

  it("applies a new skill at once, and refuses a change through its own action", async () => {
    state.changes = [change({ skill_id: null })];
    render(<ProposedChanges canEdit />);

    await userEvent.click(screen.getByRole("button", { name: /Apply the change to refunds/ }));
    expect(state.apply).toHaveBeenCalledWith(expect.objectContaining({ id: "p-1", revision: 1 }));

    await userEvent.click(screen.getByRole("button", { name: /Discard the change to refunds/ }));
    expect(state.discard).toHaveBeenCalledWith(expect.objectContaining({ id: "p-1", revision: 1 }));
  });

  it("sends a change to a skill agents use through a check on them, on its line", async () => {
    // Applying it goes live for every agent that follows the line, so it is
    // checked there first; there is no Apply that skips the check.
    state.changes = [change({ fork_id: "fork-1" })];
    render(<ProposedChanges canEdit />);

    expect(screen.queryByRole("button", { name: /Apply the change to refunds/ })).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: /Check the change to refunds on the agents/ }),
    );
    expect(screen.getByText("checking p-1 on fork-1")).toBeInTheDocument();
  });
});

it("hides cached proposal text after permission to read runs is removed", () => {
  state.runsView = false;
  state.changes = [change()];
  const { container } = render(<ProposedChanges canEdit />);
  expect(container).toBeEmptyDOMElement();
});
