import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { hunk } from "@/test-utils/authoring";
import { SuggestionCard } from "./suggestion-card";

describe("SuggestionCard", () => {
  it("shows the change in its surroundings, why, and the evidence behind it", () => {
    render(<SuggestionCard hunk={hunk()} canEdit busy={false} onDecide={vi.fn()} />);
    expect(screen.getByText("Be brief. Refunds take 30 days.")).toBeInTheDocument();
    expect(screen.getByText("You answer refunds.")).toBeInTheDocument();
    expect(screen.getByText("Readers corrected the refund window.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "run run-0123" })).toHaveAttribute(
      "href",
      "/runs?run=run-0123456789",
    );
  });

  it("accepts, dismisses, or accepts the person's own wording", async () => {
    const onDecide = vi.fn();
    render(<SuggestionCard hunk={hunk()} canEdit busy={false} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByRole("textbox", { name: "Your wording of the suggestion" });
    await userEvent.clear(box);
    await userEvent.type(box, "Thirty days.");
    await userEvent.click(screen.getByRole("button", { name: "Save and accept" }));
    expect(onDecide.mock.calls).toEqual([
      [{ action: "accept" }],
      [{ action: "dismiss" }],
      [{ action: "accept", text: "Thirty days." }],
    ]);
  });

  it("can leave the edit without deciding", async () => {
    render(<SuggestionCard hunk={hunk()} canEdit busy={false} onDecide={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("offers only Dismiss for a suggestion the draft has moved past", () => {
    render(
      <SuggestionCard hunk={hunk({ applies: false })} canEdit busy={false} onDecide={vi.fn()} />,
    );
    expect(screen.getByText("No longer fits the draft")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("offers Undo on a decided suggestion, shows what was accepted, and nothing to a reader", async () => {
    const onDecide = vi.fn();
    const { rerender } = render(
      <SuggestionCard
        hunk={hunk({ status: "accepted", accepted_text: "Thirty days.", origin: "verify" })}
        canEdit
        busy={false}
        onDecide={onDecide}
      />,
    );
    expect(screen.getByText("Thirty days.")).toBeInTheDocument();
    expect(screen.getByText("From verifying your edits")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onDecide).toHaveBeenCalledWith({ action: "undo" });
    rerender(
      <SuggestionCard
        hunk={hunk({ status: "accepted", accepted_text: null, applies: false })}
        canEdit
        busy={false}
        onDecide={onDecide}
      />,
    );
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    expect(screen.getByText("Be brief. Refunds take 30 days.")).toBeInTheDocument();
    rerender(
      <SuggestionCard
        hunk={hunk({ status: "dismissed" })}
        canEdit={false}
        busy={false}
        onDecide={onDecide}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows a tool's proposed name and description against what it was", () => {
    render(
      <SuggestionCard
        hunk={hunk({
          kind: "tool_override",
          capability_id: "charts",
          tool_id: "create_chart",
          new_name: "draw_chart",
          new_description: "Draw a chart of the numbers asked about.",
          base_description: null,
        })}
        canEdit
        busy={false}
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByText("Tool create_chart")).toBeInTheDocument();
    expect(screen.getByText("draw_chart")).toBeInTheDocument();
    expect(screen.getByText("Draw a chart of the numbers asked about.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("shows a tool change that renames only, or describes a named tool", () => {
    const { rerender } = render(
      <SuggestionCard
        hunk={hunk({ kind: "tool_override", tool_id: null, new_name: "x", new_description: null })}
        canEdit
        busy={false}
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByText("Tool")).toBeInTheDocument();
    rerender(
      <SuggestionCard
        hunk={hunk({
          kind: "tool_override",
          tool_id: "t",
          base_name: "old_name",
          new_name: "new_name",
          new_description: "d",
          base_description: "before",
        })}
        canEdit
        busy={false}
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByText("old_name")).toBeInTheDocument();
    expect(screen.getByText("before")).toBeInTheDocument();
  });
});
