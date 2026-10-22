import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { batch, hunk } from "@/test-utils/authoring";
import { SuggestionList } from "./suggestion-list";

vi.mock("./check-run-verdicts", () => ({
  CheckRunVerdicts: ({ runIds }: { runIds: string[] }) => <p>{`verdicts ${runIds.join(",")}`}</p>,
}));

describe("SuggestionList", () => {
  it("puts waiting suggestions first, says what they should change, and links the checks", async () => {
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
    expect(screen.getByRole("link", { name: "run 1" })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/eval-1",
    );
    expect(screen.getByText("verdicts eval-1")).toBeInTheDocument();
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
    expect(screen.getByText("Mine.")).toBeInTheDocument();

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
