import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { batch, hunk } from "@/test-utils/authoring";
import { SuggestionList } from "./suggestion-list";

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
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(onDecide).toHaveBeenCalledWith(expect.objectContaining({ id: "waiting" }), {
      action: "accept",
    });
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
