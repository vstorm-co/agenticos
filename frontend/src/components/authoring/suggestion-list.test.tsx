import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { diffLine } from "@/test-utils/diff";

import { authoringRequest, batch, hunk } from "@/test-utils/authoring";
import { SuggestionList } from "./suggestion-list";

vi.mock("./check-result", () => ({
  CheckResults: ({ runIds }: { runIds: string[] }) => <p>{`checks ${runIds.join(",")}`}</p>,
}));

const actions = () => ({ busy: false, onDecide: vi.fn(), onDecideIdea: vi.fn() });

describe("SuggestionList", () => {
  it("says what the batch should change, states the checks, and opens on what waits", async () => {
    const props = actions();
    render(
      <SuggestionList
        batch={batch({
          hunks: [
            hunk({ id: "done", status: "dismissed", new_text: "Decided one." }),
            hunk({ id: "waiting", new_text: "Waiting one." }),
          ],
          check_eval_run_ids: ["eval-1"],
        })}
        request={null}
        agentId="agent-1"
        actions={props}
      />,
    );
    expect(screen.getByRole("tab", { name: "To review 1" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Decided 1" })).toBeInTheDocument();
    const cards = screen.getAllByTestId("suggestion");
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveTextContent("Waiting one.");
    expect(screen.getByText("Refund answers name 30 days")).toBeInTheDocument();
    expect(screen.getByText("Checked with evals:")).toBeInTheDocument();
    expect(screen.getByText("checks eval-1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(props.onDecide).toHaveBeenCalledWith(expect.objectContaining({ id: "waiting" }), {
      action: "accept",
    });
  });

  it("leaves the editor behind once an edited suggestion is accepted, and after an undo", async () => {
    const props = { agentId: "agent-1", request: null, actions: actions() };
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
    await userEvent.click(screen.getByRole("button", { name: /Instructions/ }));
    expect(screen.getByText(diffLine("Mine."))).toBeInTheDocument();

    rerender(<SuggestionList batch={batch({ hunks: [waiting] })} {...props} />);
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("is read-only once a newer request replaced it, its waiting ones decided by nobody", async () => {
    render(
      <SuggestionList
        batch={batch({ status: "superseded", expected_effect: "" })}
        request={null}
        agentId="agent-1"
        actions={actions()}
      />,
    );
    expect(
      screen.getByText("A newer request replaced these suggestions. They are kept as a record."),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Decided 1" })).toHaveAttribute("aria-selected", "true");
    const folded = screen.getByTestId("decided-change");
    expect(folded).toHaveTextContent("Not decided");
    await userEvent.click(within(folded).getByRole("button"));
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });

  it("lists new-skill ideas from the request when no batch was recorded", () => {
    render(
      <SuggestionList
        batch={null}
        request={authoringRequest({
          report: {
            rejected: [
              {
                kind: "create_skill",
                reason: "insufficient_evidence",
                change: { name: "returns", description: "Explain returns", content: "Ask first." },
              },
            ],
          },
        })}
        agentId="agent-1"
        actions={actions()}
      />,
    );
    expect(screen.getByRole("tab", { name: "To review 1" })).toBeInTheDocument();
    expect(screen.getByTestId("idea")).toHaveTextContent("returns");
    expect(screen.queryByText("Checked with evals:")).toBeNull();
  });
});

it("describes linked evidence instead of displaying raw run identities in the expected effect", () => {
  const id = "467abd40-2539-49d3-b239-2c960f7b7b07";
  render(
    <SuggestionList
      agentId="agent-1"
      request={null}
      actions={actions()}
      batch={batch({
        expected_effect: `Improve run ${id}`,
        hunks: [hunk({ evidence: [{ run_id: id, quote: "Wrong" }] })],
      })}
    />,
  );
  expect(screen.getByText(/Proposed to address problems in 1 source answer/)).toBeInTheDocument();
  expect(screen.queryByText(`Improve run ${id}`)).not.toBeInTheDocument();
});
