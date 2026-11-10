import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { authoringRequest, batch, hunk } from "@/test-utils/authoring";
import { SuggestionTabs } from "./suggestion-tabs";

const actions = () => ({ busy: false, onDecide: vi.fn(), onDecideIdea: vi.fn() });

function selected() {
  return screen.getByRole("tab", { selected: true }).textContent;
}

describe("SuggestionTabs", () => {
  it("opens on To review and keeps the tab a person chose", async () => {
    const waiting = batch({ hunks: [hunk({ id: "w" })] });
    const { rerender } = render(
      <SuggestionTabs batch={waiting} request={null} actions={actions()} />,
    );
    expect(screen.getByRole("tablist", { name: "Suggestions" })).toBeInTheDocument();
    expect(selected()).toBe("To review 1");
    expect(screen.getByTestId("suggestion")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Decided 0" }));
    expect(screen.getByText("Nothing decided yet.")).toBeInTheDocument();

    rerender(
      <SuggestionTabs
        batch={batch({ hunks: [hunk({ id: "w", status: "dismissed" })] })}
        request={null}
        actions={actions()}
      />,
    );
    expect(selected()).toBe("Decided 1");
    await userEvent.click(screen.getByRole("tab", { name: "To review 0" }));
    expect(screen.getByText("Nothing left to review.")).toBeInTheDocument();
  });

  it("keeps the chosen tab in the address, so Back to the agent returns to it", async () => {
    window.history.replaceState({}, "", "/agents/a1");
    render(
      <SuggestionTabs
        batch={batch({ hunks: [hunk({ id: "w" })] })}
        request={null}
        actions={actions()}
      />,
    );
    await userEvent.click(screen.getByRole("tab", { name: "Decided 0" }));
    expect(new URL(window.location.href).searchParams.get("suggestions")).toBe("decided");
  });

  it("opens on Decided, saying nothing is left, once every change is decided", () => {
    render(
      <SuggestionTabs
        batch={batch({ hunks: [hunk({ status: "accepted" })] })}
        request={authoringRequest({
          report: {
            rejected: [
              {
                kind: "create_skill",
                reason: "insufficient_evidence",
                change: { name: "returns", content: "Ask first." },
                skill_id: "skill-1",
              },
              { kind: "instructions", reason: "unanchored", change: { old_text: "Gone." } },
            ],
          },
        })}
        actions={actions()}
      />,
    );
    expect(selected()).toBe("Decided 2");
    expect(screen.getByText("Nothing left to review.")).toBeInTheDocument();
    expect(screen.getAllByTestId("decided-change")).toHaveLength(2);
  });

  it("shows nothing when the assistant left nothing to decide", () => {
    const { container } = render(
      <SuggestionTabs
        batch={null}
        request={authoringRequest({ report: { rejected: [] } })}
        actions={actions()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
