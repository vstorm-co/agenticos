import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { diffLine } from "@/test-utils/diff";

import { batch, hunk } from "@/test-utils/authoring";
import { SuggestionList } from "./suggestion-list";

vi.mock("./check-result", () => ({
  CheckResults: ({ runIds }: { runIds: string[] }) => <p>{`checks ${runIds.join(",")}`}</p>,
}));

describe("SuggestionList", () => {
  it("puts waiting suggestions first, says what they should change, and states the checks", async () => {
    const onDecide = vi.fn();
    render(
      <SuggestionList
        batch={batch({
          hunks: [
            hunk({ id: "done", status: "dismissed", new_text: "Decided one." }),
            hunk({ id: "waiting", new_text: "Waiting one." }),
          ],
          check_eval_run_ids: ["eval-1"],
        })}
        agentId="agent-1"
        busy={false}
        onDecide={onDecide}
      />,
    );
    const cards = screen.getAllByTestId("suggestion");
    expect(cards[0]).toHaveTextContent("Waiting one.");
    expect(screen.getByText("Refund answers name 30 days")).toBeInTheDocument();
    expect(screen.getByText("Checked with evals:")).toBeInTheDocument();
    expect(screen.getByText("checks eval-1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(onDecide).toHaveBeenCalledWith(expect.objectContaining({ id: "waiting" }), {
      action: "accept",
    });
  });

  it("leaves the editor behind once an edited suggestion is accepted, and after an undo", async () => {
    const props = { agentId: "agent-1", busy: false, onDecide: vi.fn() };
    const waiting = hunk({ id: "h-1", new_text: "Waiting one." });
    const { rerender } = render(<SuggestionList batch={batch({ hunks: [waiting] })} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("textbox")).toBeInTheDocument();

    rerender(
      <SuggestionList
        batch={batch({ hunks: [{ ...waiting, status: "accepted", accepted_text: "Mine." }] })}
        {...props}
      />,
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText(diffLine("Mine."))).toBeInTheDocument();

    rerender(<SuggestionList batch={batch({ hunks: [waiting] })} {...props} />);
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("is read-only once a newer request replaced it", () => {
    render(
      <SuggestionList
        batch={batch({ status: "superseded", expected_effect: "" })}
        agentId="agent-1"
        busy={false}
        onDecide={vi.fn()}
      />,
    );
    expect(
      screen.getByText("A newer request replaced these suggestions. They are kept as a record."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

it("describes linked evidence instead of displaying raw run identities in the expected effect", () => {
  const id = "467abd40-2539-49d3-b239-2c960f7b7b07";
  render(
    <SuggestionList
      agentId="agent-1"
      busy={false}
      onDecide={vi.fn()}
      batch={batch({
        expected_effect: `Improve run ${id}`,
        hunks: [hunk({ evidence: [{ run_id: id, quote: "Wrong" }] })],
      })}
    />,
  );
  expect(screen.getByText(/Proposed to address problems in 1 source answer/)).toBeInTheDocument();
  expect(screen.queryByText(`Improve run ${id}`)).not.toBeInTheDocument();
});
