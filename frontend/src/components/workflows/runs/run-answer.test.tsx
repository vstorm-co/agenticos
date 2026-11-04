import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RunAnswer } from "./run-answer";

const FILE = { id: "f1", filename: "report.csv" };

describe("RunAnswer", () => {
  it("shows the answer's text, the passages it drew on and the files it made", async () => {
    render(
      <RunAnswer
        output={{
          text: "Ada scored highest.",
          sources: [
            { filename: "scores.pdf", collection: "hr", page: 3, score: 0.9, content: "…" },
            { filename: "notes.md", collection: "hr", page: null, score: 0.5, content: "…" },
          ],
          artifacts: [FILE, FILE],
          structured: null,
        }}
      />,
    );

    expect(screen.getByText("Ada scored highest.", { selector: "p" })).toBeTruthy();
    expect(screen.getByText("2 sources")).toBeTruthy();
    expect(screen.getByText("scores.pdf · hr · page 3")).toBeTruthy();
    expect(screen.getByText("notes.md · hr")).toBeTruthy();
    expect(screen.getByText("2 files, listed under Files")).toBeTruthy();

    const raw = screen.getByText("Raw output").closest("details");
    expect(raw).not.toHaveAttribute("open");
    await userEvent.click(screen.getByText("Raw output"));
    expect(raw).toHaveAttribute("open");
  });

  it("shows a structured result as JSON, with nothing else missing", () => {
    render(<RunAnswer output={{ structured: { winner: "Ada" } }} />);
    // Once as the result, once in the folded raw output.
    expect(screen.getAllByText(/winner/)).toHaveLength(2);
    expect(screen.queryByText(/sources?$/)).toBeNull();
  });

  it("answers with a called workflow's answer handed on as the structured result", () => {
    render(
      <RunAnswer
        output={{
          text: null,
          sources: [],
          artifacts: [],
          structured: { text: "Ada", sources: [], artifacts: [], structured: null },
        }}
      />,
    );
    expect(screen.getByText("Ada", { selector: "p" })).toBeTruthy();
  });

  it("keeps a structured result shaped like an answer when the run said more", () => {
    render(
      <RunAnswer
        output={{ text: "Done.", structured: { text: "Ada", sources: [], artifacts: [] } }}
      />,
    );
    expect(screen.getByText("Done.", { selector: "p" })).toBeTruthy();
    expect(screen.queryByText("Ada", { selector: "p" })).toBeNull();
  });

  it("says the run answered with nothing, and offers no JSON to open", () => {
    render(<RunAnswer output={{ text: null, sources: [], artifacts: [], structured: null }} />);
    expect(screen.getByText("The run finished without an answer.")).toBeTruthy();
    expect(screen.queryByText("Raw output")).toBeNull();
  });

  it.each([
    ["a key the Output step does not write", { text: "hi", extra: 1 }],
    ["text that is not text", { text: 3 }],
    ["a structured result that is not an object", { structured: [1] }],
    ["sources that are not a list", { sources: "scores.pdf" }],
    ["artifacts that are not a list", { artifacts: {} }],
    ["a source with no file", { sources: [{ collection: "hr" }] }],
    ["a source that is not an object", { sources: ["scores.pdf"] }],
  ])("shows %s as the JSON it is", (_, output) => {
    render(<RunAnswer output={output} />);
    expect(screen.queryByText("Raw output")).toBeNull();
    expect(screen.queryByText("The run finished without an answer.")).toBeNull();
    expect(document.querySelector(".font-mono")).not.toBeNull();
  });
});
