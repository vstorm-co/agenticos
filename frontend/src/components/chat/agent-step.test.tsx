import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AgentStep, AgentSteps } from "./agent-step";

function step(label: string) {
  return <AgentStep key={label} label={label} kind="tool" state="done" expanded={false} />;
}

/**
 * A run of steps beside a turn.
 *
 * The property worth holding: a turn's work does not push its answer off the screen.
 * The step that matters is the current one while it runs and the last one afterwards,
 * so that is what stays open - and what folds says how much folded, because a run that
 * silently showed one step would read as a turn that only did one thing.
 */
describe("a run of steps", () => {
  it("keeps the last step open and folds the earlier ones", () => {
    render(<AgentSteps>{["Listed /workspace", "Read a.md", "Wrote b.md"].map(step)}</AgentSteps>);

    expect(screen.getByText("Wrote b.md")).toBeVisible();
    expect(screen.queryByText("Read a.md")).toBeNull();
    expect(screen.getByRole("button", { name: /2 earlier steps/ })).toBeVisible();
  });

  it("opens the folded steps when asked", async () => {
    render(<AgentSteps>{["Listed /workspace", "Read a.md", "Wrote b.md"].map(step)}</AgentSteps>);

    await userEvent.click(screen.getByRole("button", { name: /2 earlier steps/ }));

    expect(screen.getByText("Listed /workspace")).toBeVisible();
    expect(screen.getByText("Read a.md")).toBeVisible();
  });

  it("folds nothing when there is only one earlier step", () => {
    // A control that costs a line to save a line is not a saving.
    render(<AgentSteps>{["Read a.md", "Wrote b.md"].map(step)}</AgentSteps>);

    expect(screen.getByText("Read a.md")).toBeVisible();
    expect(screen.queryByText(/earlier step/)).toBeNull();
  });

  it("shows every step when the run holds something a person has to answer", () => {
    // A call that failed, or one waiting for approval. Folding that away hides the one
    // line in the turn that was asking for something.
    render(
      <AgentSteps showAll>{["Listed /workspace", "Read a.md", "Wrote b.md"].map(step)}</AgentSteps>,
    );

    expect(screen.getByText("Listed /workspace")).toBeVisible();
    expect(screen.queryByText(/earlier steps/)).toBeNull();
  });

  it("closes a finished run of several with Done", () => {
    render(<AgentSteps done>{["Read a.md", "Wrote b.md"].map(step)}</AgentSteps>);

    expect(screen.getByText("Done")).toBeVisible();
  });
});

/**
 * One step.
 *
 * A row, not a card: no border, no fill, no tick on every line. What earns a marker is
 * the exception, which is what makes a marker mean anything.
 */
describe("one step", () => {
  it("is plain text when it has nothing to open", () => {
    render(<AgentStep label="Available Skills" kind="skill" state="done" expanded={false} />);

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByText("Available Skills")).toBeVisible();
  });

  it("opens into whatever it was given", () => {
    render(
      <AgentStep label="Read a.md" kind="read" state="done" expanded onToggle={() => {}}>
        <p>the contents</p>
      </AgentStep>,
    );

    expect(screen.getByText("the contents")).toBeVisible();
    expect(screen.getByRole("button", { name: /Read a.md/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("marks a failure and a call parked for approval, and nothing else", () => {
    const { unmount } = render(
      <AgentStep label="Ran pytest" kind="shell" state="error" expanded={false} />,
    );
    expect(screen.getByLabelText("Failed")).toBeInTheDocument();
    unmount();

    const parked = render(
      <AgentStep label="Ran pytest" kind="shell" state="parked" expanded={false} />,
    );
    expect(screen.getByText("waiting for approval")).toBeVisible();
    expect(screen.queryByLabelText("Running")).toBeNull();
    parked.unmount();

    render(<AgentStep label="Ran pytest" kind="shell" state="done" expanded={false} />);
    expect(screen.queryByLabelText("Failed")).toBeNull();
    expect(screen.queryByLabelText("Running")).toBeNull();
  });

  it("wears an MCP server's own logo instead of a generic icon", () => {
    // A row of identical wrenches says nothing about which product a side effect
    // landed in.
    render(
      <AgentStep
        label="Linear · Create issue"
        logoDomain="linear.app"
        kind="mcp"
        state="done"
        expanded={false}
      />,
    );

    expect(screen.getByRole("presentation", { hidden: true })).toBeInTheDocument();
  });
});
