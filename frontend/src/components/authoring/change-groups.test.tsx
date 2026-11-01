import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { hunk } from "@/test-utils/authoring";
import type { RejectedChange } from "@/types/authoring";
import { ChangeGroups, type Entry } from "./change-groups";

const actions = (overrides = {}) => ({
  open: true,
  busy: false,
  onDecide: vi.fn(),
  onDecideIdea: vi.fn(),
  ...overrides,
});

const idea = (overrides: Partial<RejectedChange> = {}): RejectedChange => ({
  kind: "create_skill",
  reason: "insufficient_evidence",
  change: { name: "returns", description: "Explain returns", content: "Ask first." },
  ...overrides,
});

function headings() {
  return screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);
}

describe("ChangeGroups", () => {
  it("groups waiting changes by kind, each group counted, and shows each whole", () => {
    const entries: Entry[] = [
      { idea: idea(), index: 2, requestId: "request-1" },
      { hunk: hunk({ id: "a", kind: "tool_override", tool_id: "search" }) },
      { hunk: hunk({ id: "b" }) },
      { hunk: hunk({ id: "c", kind: "spec_field", path: "max_steps", new_value: 8 }) },
    ];
    render(<ChangeGroups entries={entries} decided={false} actions={actions()} />);
    expect(headings()).toEqual([
      "Instructions 1",
      "Tool descriptions 1",
      "Settings 1",
      "New skills 1",
    ]);
    expect(screen.getAllByTestId("suggestion")).toHaveLength(3);
    expect(screen.getByTestId("idea")).toHaveTextContent("returns");
    expect(screen.queryByTestId("decided-change")).toBeNull();
  });

  it("folds a decided change to its kind, how it was decided and what it was for", async () => {
    const entries: Entry[] = [
      {
        hunk: hunk({
          id: "a",
          status: "accepted",
          accepted_text: "Mine.",
          expected_effect: "Right window. More.",
        }),
      },
      { hunk: hunk({ id: "b", status: "accepted", accepted_text: hunk().new_text }) },
      { hunk: hunk({ id: "c", status: "dismissed" }) },
      {
        hunk: hunk({
          id: "d",
          kind: "tool_override",
          status: "accepted",
          tool_id: "search",
          base_name: "Search the web",
        }),
      },
      { hunk: hunk({ id: "e", kind: "tool_override", status: "dismissed", tool_id: "fetch" }) },
      { hunk: hunk({ id: "f", kind: "tool_override", status: "dismissed" }) },
      {
        hunk: hunk({
          id: "g",
          kind: "spec_field",
          status: "accepted",
          path: "model_settings/temperature",
          new_value: 0.2,
          accepted_value: 0.2,
        }),
      },
      {
        hunk: hunk({ id: "h", kind: "spec_field", status: "dismissed", path: "model_profile_id" }),
      },
      { hunk: hunk({ id: "i", kind: "create_skill", status: "dismissed" }) },
    ];
    render(<ChangeGroups entries={entries} decided actions={actions()} />);
    const rows = screen.getAllByTestId("decided-change").map((row) => row.textContent);
    expect(rows).toEqual([
      "InstructionsEdited and acceptedRight window.",
      "InstructionsAcceptedReaders corrected the refund window.",
      "InstructionsDismissedReaders corrected the refund window.",
      "Tool description: Search the webAcceptedReaders corrected the refund window.",
      "Tool description: fetchDismissedReaders corrected the refund window.",
      "Tool description: DismissedReaders corrected the refund window.",
      "Setting: TemperatureAcceptedReaders corrected the refund window.",
      "ModelDismissedReaders corrected the refund window.",
      "New skillDismissedReaders corrected the refund window.",
    ]);
    const first = within(screen.getAllByTestId("decided-change")[0]!).getByRole("button");
    expect(first).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("suggestion")).toBeNull();
    await userEvent.click(first);
    expect(first).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("suggestion")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    await userEvent.click(first);
    expect(screen.queryByTestId("suggestion")).toBeNull();
  });

  it("folds a created or dismissed idea, and undoes a dismissal on its request", async () => {
    const props = actions();
    const entries: Entry[] = [
      { idea: idea({ skill_id: "skill-1" }), index: 0, requestId: "request-1" },
      {
        idea: idea({ dismissed: true, change: { content: "Ask." } }),
        index: 3,
        requestId: "request-1",
      },
    ];
    render(<ChangeGroups entries={entries} decided actions={props} />);
    const [created, dismissed] = screen.getAllByTestId("decided-change");
    expect(created).toHaveTextContent("New skillCreatedreturns");
    expect(dismissed!.textContent).toBe("New skillDismissed");
    await userEvent.click(within(created!).getByRole("button"));
    expect(screen.getByRole("link", { name: "Open the skill" })).toHaveAttribute(
      "href",
      "/skills/skill-1",
    );
    await userEvent.click(within(dismissed!).getByRole("button"));
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(props.onDecideIdea).toHaveBeenCalledWith("request-1", 3, "undo");
  });

  it("creates and dismisses a waiting idea through its request and place", async () => {
    const onCreateIdea = vi.fn().mockResolvedValue(true);
    const props = actions({ onCreateIdea });
    render(
      <ChangeGroups
        entries={[{ idea: idea(), index: 2, requestId: "request-1" }]}
        decided={false}
        actions={props}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(props.onDecideIdea).toHaveBeenCalledWith("request-1", 2, "dismiss");
    await userEvent.click(screen.getByRole("button", { name: "Create skill" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create skill" }));
    expect(onCreateIdea).toHaveBeenCalledWith(
      "request-1",
      2,
      expect.objectContaining({ name: "returns" }),
    );
  });

  it("decides a waiting suggestion through its hunk", async () => {
    const props = actions();
    const waiting = hunk({ id: "w" });
    render(<ChangeGroups entries={[{ hunk: waiting }]} decided={false} actions={props} />);
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(props.onDecide).toHaveBeenCalledWith(waiting, { action: "dismiss" });
  });
});
