import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceList } from "./evidence-list";
import { VerifyReport } from "./verify-report";

describe("EvidenceList", () => {
  it("says when nothing could be checked", () => {
    render(<EvidenceList items={[]} dropped={0} />);
    expect(screen.getByText("No evidence that could be checked.")).toBeInTheDocument();
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
    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(
      screen.getByText("2 cited items could not be found in the runs and were left out."),
    ).toBeInTheDocument();
  });
});

describe("VerifyReport", () => {
  it("says when there was nothing to say", () => {
    render(<VerifyReport findings={[]} />);
    expect(
      screen.getByText("The assistant found nothing to say about your edits."),
    ).toBeInTheDocument();
  });

  it("lists each finding with what it rests on", () => {
    render(
      <VerifyReport
        findings={[
          { verdict: "supports", text: "Shorter answers help", evidence: [], evidence_dropped: 0 },
          {
            verdict: "removed",
            text: "Dropped the language rule",
            evidence: [{ run_id: "run-cccccccc", quote: "Answer in Polish" }],
            evidence_dropped: 0,
          },
          {
            verdict: "risk",
            text: "May bring back long answers",
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
  });
});
