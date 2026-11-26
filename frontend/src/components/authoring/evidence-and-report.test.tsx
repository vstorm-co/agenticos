import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConversationEvidence, EvidenceList } from "./evidence-list";
import { VerifyReport } from "./verify-report";

describe("EvidenceList", () => {
  it("says when nothing could be checked", () => {
    render(<EvidenceList items={[]} dropped={0} />);
    expect(screen.getByText("No evidence that could be checked.")).toBeInTheDocument();
  });

  it("names each run as a test question or a conversation, by the label it was read under", () => {
    render(
      <EvidenceList
        items={[
          { run_id: "q", quote: "Delivery is free", source: "test_question", number: 1 },
          { run_id: "c", quote: "Thirty days", source: "conversation", number: 1 },
          { run_id: "old", quote: "Kept before labels" },
        ]}
        dropped={0}
      />,
    );
    expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual([
      "test question 1",
      "conversation 1",
      "conversation 3",
    ]);
  });

  it("links each run, hides a quote the reader may not see, and counts what was left out", () => {
    render(
      <EvidenceList
        items={[
          { run_id: "run-aaaaaaaa", quote: "Wrong window" },
          { run_id: "run-bbbbbbbb", quote: null },
        ]}
        dropped={2}
      />,
    );
    expect(screen.getByText("Wrong window")).toBeInTheDocument();
    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/runs?run=run-aaaaaaaa",
      "/runs?run=run-bbbbbbbb",
    ]);
    expect(
      screen.getByText("2 cited items could not be found in the runs and were left out."),
    ).toBeInTheDocument();
  });
});

describe("evidence from agents the reader cannot see", () => {
  it("counts it instead of saying nothing could be checked", () => {
    render(<EvidenceList items={[]} dropped={0} hidden={2} />);
    expect(
      screen.getByText("2 cited items are from agents you cannot see and are not shown."),
    ).toBeInTheDocument();
    expect(screen.queryByText("No evidence that could be checked.")).not.toBeInTheDocument();
  });

  it("counts it beside the evidence the reader can see", () => {
    render(
      <EvidenceList items={[{ run_id: "run-a", quote: "Thirty days" }]} dropped={0} hidden={1} />,
    );
    expect(screen.getByText("Thirty days")).toBeInTheDocument();
    expect(
      screen.getByText("1 cited item is from an agent you cannot see and is not shown."),
    ).toBeInTheDocument();
  });

  it("counts it in the Improve wizard instead of saying nothing is quoted", () => {
    const { rerender } = render(<ConversationEvidence items={[]} sources={{}} hidden={2} />);
    expect(
      screen.getByText("2 cited items are from agents you cannot see and are not shown."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Nothing is quoted|No test question/)).not.toBeInTheDocument();

    rerender(<ConversationEvidence items={[]} sources={{}} />);
    expect(screen.getByText(/No test question or conversation is quoted/)).toBeInTheDocument();
  });
});

describe("VerifyReport", () => {
  it("says when there was nothing to say", () => {
    render(<VerifyReport findings={[]} />);
    expect(
      screen.getByText("The assistant found nothing to say about your edits."),
    ).toBeInTheDocument();
  });

  it("shows a finding's runs without quotes to a reader who may not see them", () => {
    render(
      <VerifyReport
        findings={[
          {
            verdict: "risk",
            text: "Dropped the brevity rule",
            evidence: [{ run_id: "run-dddddddd" }],
            evidence_dropped: 0,
          },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: "conversation 1" })).toBeInTheDocument();
    expect(document.querySelector("q")).toBeNull();
  });

  it("lists each finding with what it rests on", () => {
    render(
      <VerifyReport
        findings={[
          { verdict: "supports", text: "Shorter answers help", evidence: [], evidence_dropped: 0 },
          {
            verdict: "removed",
            text: "Dropped the language rule",
            edit: "Answer in Polish.",
            evidence: [{ run_id: "run-cccccccc", quote: "Answer in Polish" }],
            evidence_dropped: 0,
          },
          {
            verdict: "risk",
            text: "May bring back long answers",
            edit_refused: "edit_not_in_diff",
            evidence: [],
            evidence_dropped: 1,
          },
        ]}
      />,
    );
    expect(screen.getByLabelText("Supported by the evidence")).toBeInTheDocument();
    expect(screen.getByLabelText("Removed something the evidence relied on")).toBeInTheDocument();
    expect(screen.getByLabelText("A risk")).toBeInTheDocument();
    expect(screen.getByText("Answer in Polish")).toBeInTheDocument();
    // The line a quote is meant to back, so the reader can judge whether it does.
    expect(screen.getByText("About: Answer in Polish.")).toBeInTheDocument();
    expect(screen.getAllByText(/^About:/)).toHaveLength(1);
    // Shown without the line it named, and saying why.
    expect(screen.getByText("The line it names is not part of the edit")).toBeInTheDocument();
  });
});
