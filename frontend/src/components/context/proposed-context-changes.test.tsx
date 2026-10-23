import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { contextChange } from "@/test-utils/authoring";
import type { ContextChange } from "@/types/authoring";
import { ProposedContextChanges } from "./proposed-context-changes";

const state = vi.hoisted(() => ({
  changes: [] as ContextChange[],
  error: null as string | null,
  isDeciding: false,
  apply: vi.fn(),
  discard: vi.fn(),
  asked: vi.fn(),
  watch: vi.fn(),
}));

vi.mock("@/components/authoring/skill-check-button", () => ({
  ContextCheckButton: ({ proposalId }: { proposalId: string }) => (
    <button>{`check ${proposalId}`}</button>
  ),
}));
vi.mock("@/hooks/use-authoring", () => ({ useContextAuthoringWatch: state.watch }));
vi.mock("@/hooks/use-context-changes", () => ({
  useContextChanges: (status: string, options: { enabled: boolean }) => {
    state.asked(status, options);
    return {
      changes: state.changes,
      isLoading: false,
      error: state.error,
      apply: state.apply,
      discard: state.discard,
      isDeciding: state.isDeciding,
    };
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  state.changes = [contextChange()];
  state.error = null;
  state.isDeciding = false;
});

describe("ProposedContextChanges", () => {
  it("says nothing to somebody who may not edit context files, and asks for nothing", () => {
    // The list answers 403 without context:edit.
    const { container } = render(<ProposedContextChanges canEdit={false} />);
    expect(container).toBeEmptyDOMElement();
    expect(state.asked).toHaveBeenCalledWith("pending", { enabled: false });
  });

  it("keeps watching the assistant's requests once their editor has closed", () => {
    render(<ProposedContextChanges canEdit />);
    expect(state.asked).toHaveBeenCalledWith("pending", { enabled: true });
    expect(state.watch).toHaveBeenCalled();
  });

  it("is absent when nothing is waiting, and says why when the request failed", () => {
    state.changes = [];
    const { container, unmount } = render(<ProposedContextChanges canEdit />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    state.error = "403 Forbidden";
    render(<ProposedContextChanges canEdit />);
    expect(screen.getByText("403 Forbidden")).toBeVisible();
  });

  it("names the file, the agents that read it, and offers a check", () => {
    // Applying is live for every one of those agents, which is the decision.
    state.changes = [
      contextChange(),
      contextChange({ id: "change-2", context_name: "glossary", used_by: [] }),
    ];
    render(<ProposedContextChanges canEdit />);
    expect(screen.getByText(/2 changes are waiting/)).toBeVisible();
    expect(screen.getByText("house-style")).toBeVisible();
    expect(screen.getByText("Bound to Clerk")).toBeVisible();
    expect(screen.getByText("No agent you can see binds this file")).toBeVisible();
    expect(screen.getByRole("button", { name: "check change-1" })).toBeVisible();
  });

  it("keeps the change behind a click, with why, what it expects and what it rests on", async () => {
    state.changes = [
      contextChange({
        rationale: "Replies went out unsigned.",
        expected_effect: "Replies are signed.",
        evidence: [{ run_id: "run-12345678", quote: "Who wrote this?" }],
        description: "How the team writes.",
        current_description: null,
      }),
    ];
    render(<ProposedContextChanges canEdit />);
    expect(screen.queryByText("Replies went out unsigned.")).toBeNull();

    const toggle = screen.getByRole("button", { name: "Show what changes in house-style" });
    await userEvent.click(toggle);
    expect(screen.getByText("Replies went out unsigned.")).toBeVisible();
    expect(screen.getByText("Expected: Replies are signed.")).toBeVisible();
    expect(screen.getByText("Who wrote this?")).toBeVisible();
    expect(screen.getByText(/Sign as the team/)).toBeVisible();
    expect(screen.getByText(/the team writes/)).toBeVisible();

    await userEvent.click(toggle);
    expect(screen.queryByText("Replies went out unsigned.")).toBeNull();
  });

  it("applies and discards through their own actions", async () => {
    render(<ProposedContextChanges canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "Apply the change to house-style" }));
    expect(state.apply).toHaveBeenCalledWith(
      expect.objectContaining({ id: "change-1", revision: 1 }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Discard the change to house-style" }),
    );
    expect(state.discard).toHaveBeenCalledWith(
      expect.objectContaining({ id: "change-1", revision: 1 }),
    );
  });

  it("refuses to apply over a file edited since, and says what to do instead", async () => {
    state.changes = [contextChange({ stale: true, description: null })];
    render(<ProposedContextChanges canEdit />);
    expect(screen.getByText("File changed since")).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply the change to house-style" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard the change to house-style" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Show what changes in house-style" }));
    expect(screen.getByText(/edit the file by hand/)).toBeVisible();
  });

  it("holds both decisions while one is on its way", () => {
    state.isDeciding = true;
    render(<ProposedContextChanges canEdit />);
    expect(screen.getByRole("button", { name: "Apply the change to house-style" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Discard the change to house-style" }),
    ).toBeDisabled();
  });
});
