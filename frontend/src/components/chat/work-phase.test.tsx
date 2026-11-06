import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { reasoningSections, WorkPhase } from "./work-phase";

describe("reasoning section titles", () => {
  it("extracts bold and ATX headings without dropping their explanations", () => {
    expect(
      reasoningSections(
        "**Investigating projects**\n\nCheck the instructions.\n\n### Comparing boards\nFind blockers.",
      ),
    ).toEqual([
      { title: "Investigating projects", body: "Check the instructions." },
      { title: "Comparing boards", body: "Find blockers." },
    ]);
  });
  it("preserves plain reasoning, inline emphasis and unfinished streamed headings", () => {
    for (const body of ["Inspect **these projects** first.", "**Investigating", "No heading here."])
      expect(reasoningSections(body)).toEqual([{ body }]);
    expect(reasoningSections("")).toEqual([]);
  });
  it("keeps fenced code and overlong bold paragraphs as content", () => {
    const code = "```markdown\n# Not a phase\n**Neither is this**\n```";
    expect(reasoningSections(code)).toEqual([{ body: code }]);
    const long = `**${"x".repeat(141)}**`;
    expect(reasoningSections(long)).toEqual([{ body: long }]);
  });
  it("keeps a preface and consecutive headings in order", () => {
    expect(reasoningSections("First inspect.\n**Read**\n**Compare**\nCheck differences.")).toEqual([
      { body: "First inspect." },
      { title: "Read", body: "" },
      { title: "Compare", body: "Check differences." },
    ]);
  });
});

it("keeps a named phase and its tools collapsed together", async () => {
  const { container } = render(
    <WorkPhase
      title="Investigating project details"
      body="Read the instructions."
      steps={3}
      running={false}
    >
      <span>Get project</span>
    </WorkPhase>,
  );
  expect(container.querySelector("details")).not.toHaveAttribute("open");
  expect(screen.getByText("3 actions")).toBeVisible();
  expect(screen.getByText("Get project")).not.toBeVisible();
  await userEvent.click(screen.getByText("Investigating project details"));
  expect(screen.getByText("Get project")).toBeVisible();
  expect(screen.getByText("Read the instructions.")).toBeVisible();
});

it.each([
  {
    waiting: "awaiting_approval" as const,
    failed: false,
    stopped: false,
    label: "Waiting for approval",
  },
  { waiting: undefined, failed: true, stopped: false, label: "Failed" },
  { waiting: undefined, failed: false, stopped: true, label: "Did not finish" },
])("keeps $label visible while the phase is collapsed", ({ label, ...state }) => {
  render(
    <WorkPhase title="Checking projects" body="" steps={1} running={false} {...state}>
      {null}
    </WorkPhase>,
  );
  expect(screen.getByText(label)).toBeVisible();
});
