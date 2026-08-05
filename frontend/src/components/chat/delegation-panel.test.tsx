import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DelegationPanels } from "./delegation-panel";
import type { Delegation } from "@/types";

// The renderer is tested on its own; here the delegate's answer only has to be
// identifiable, and the real one is loaded through `next/dynamic`.
vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));
// Panels are what this file is about, not who may open a run. The link that
// permission gates is proved through the real hook in
// `delegation-panel.integration.test.tsx`.
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));

function delegation(overrides: Partial<Delegation> = {}): Delegation {
  return {
    taskId: "t1",
    subagent: "researcher",
    depth: 0,
    mode: "sync",
    prompt: "find three papers on retrieval",
    parentTaskId: null,
    status: "running",
    text: "",
    thinking: "",
    steps: [],
    runId: null,
    costUsd: null,
    inputTokens: null,
    outputTokens: null,
    error: null,
    ...overrides,
  };
}

describe("DelegationPanels - one panel per delegation", () => {
  it("draws nothing when the turn delegated nothing", () => {
    const { container } = render(<DelegationPanels delegations={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("gives three concurrent specialists three panels, not one paragraph", () => {
    render(
      <DelegationPanels
        delegations={[
          delegation({ taskId: "t1", subagent: "researcher", text: "found three" }),
          delegation({ taskId: "t2", subagent: "writer", text: "once upon a time" }),
          delegation({ taskId: "t3", subagent: "critic", text: "too long" }),
        ]}
      />,
    );

    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(3);
    expect(screen.getAllByTestId("markdown").map((node) => node.textContent)).toEqual([
      "found three",
      "once upon a time",
      "too long",
    ]);
  });

  it("shows who is working and what they were asked", () => {
    // A delegation whose brief nobody can see is a black box that costs money.
    render(<DelegationPanels delegations={[delegation()]} />);

    expect(screen.getByText("researcher")).toBeInTheDocument();
    expect(screen.getByText("working…")).toBeInTheDocument();
    expect(screen.getByText("find three papers on retrieval")).toBeInTheDocument();
  });

  it("says when a delegation runs in the background", () => {
    // Its frames arrive after the parent has answered, so a panel that did not say
    // so would read as an answer that never came.
    render(<DelegationPanels delegations={[delegation({ mode: "async" })]} />);

    expect(screen.getByText("Background")).toBeInTheDocument();
  });
});

describe("DelegationPanels - open while it runs, closed once it is over", () => {
  it("opens a running delegation", () => {
    render(<DelegationPanels delegations={[delegation({ text: "half an answ" })]} />);

    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
    expect(screen.getByTestId("markdown")).toBeInTheDocument();
  });

  it("closes the panel when the delegation reports, keeping the header", () => {
    const { rerender } = render(<DelegationPanels delegations={[delegation({ text: "done" })]} />);
    expect(screen.getByTestId("markdown")).toBeInTheDocument();

    rerender(
      <DelegationPanels
        delegations={[
          delegation({ status: "completed", text: "done", costUsd: 0.0042, inputTokens: 1200 }),
        ]}
      />,
    );

    expect(screen.queryByTestId("markdown")).toBeNull();
    expect(screen.getByText("researcher")).toBeInTheDocument();
    expect(screen.getByText("finished")).toBeInTheDocument();
    expect(screen.getByText("$0.0042")).toBeInTheDocument();
  });

  it("mounts an already-finished delegation closed", () => {
    // A conversation reopened after a turn that delegated: nobody is watching it
    // happen, so it is a line rather than a wall of somebody else's transcript.
    render(<DelegationPanels delegations={[delegation({ status: "completed", text: "done" })]} />);

    expect(screen.getByRole("button", { expanded: false })).toBeInTheDocument();
    expect(screen.queryByTestId("markdown")).toBeNull();
  });

  it("opens on click and closes again", async () => {
    render(<DelegationPanels delegations={[delegation({ status: "completed", text: "done" })]} />);
    const header = screen.getByRole("button");

    await userEvent.click(header);
    expect(screen.getByTestId("markdown")).toBeInTheDocument();

    await userEvent.click(header);
    expect(screen.queryByTestId("markdown")).toBeNull();
  });

  it("leaves a panel alone while it is still running", () => {
    // The status-transition check must not close a panel on every re-render, which
    // is what a streaming delegation produces one of per delta.
    const { rerender } = render(<DelegationPanels delegations={[delegation({ text: "a" })]} />);
    rerender(<DelegationPanels delegations={[delegation({ text: "ab" })]} />);

    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
    expect(screen.getByTestId("markdown")).toHaveTextContent("ab");
  });
});

describe("DelegationPanels - how a delegation ended", () => {
  it("says why a delegation failed instead of showing an empty panel", async () => {
    render(
      <DelegationPanels
        delegations={[delegation({ status: "failed", error: "the provider refused" })]}
      />,
    );

    expect(screen.getByText("failed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByText("the provider refused")).toBeInTheDocument();
  });

  it("marks a delegation the run never got to finish", () => {
    render(<DelegationPanels delegations={[delegation({ status: "cancelled" })]} />);

    expect(screen.getByText("stopped")).toBeInTheDocument();
  });

  it("reports the tokens behind the cost, and zero for a run that measured none", () => {
    render(
      <DelegationPanels
        delegations={[
          delegation({ taskId: "t1", status: "completed", costUsd: 0.5, inputTokens: 10 }),
          delegation({ taskId: "t2", status: "completed", costUsd: 0.25 }),
        ]}
      />,
    );

    expect(screen.getByText("$0.5000")).toHaveAttribute("title", "10 input · 0 output tokens");
    expect(screen.getByText("$0.2500")).toHaveAttribute("title", "0 input · 0 output tokens");
  });

  it("says nothing about cost when nothing was measured", () => {
    render(<DelegationPanels delegations={[delegation({ status: "completed" })]} />);

    expect(screen.queryByTitle(/tokens/)).toBeNull();
  });
});

describe("DelegationPanels - the delegate's own work", () => {
  it("narrates the delegate's tool calls, which the parent's transcript cannot", () => {
    render(
      <DelegationPanels
        delegations={[
          delegation({
            steps: [
              { id: "c1", name: "search_documents", ok: true },
              { id: "c2", name: "search_documents", ok: null },
              { id: "c3", name: "fetch_url", ok: false },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText("Knowledge Base Search")).toBeInTheDocument();
    expect(screen.getByText("Searching the documents")).toBeInTheDocument();
    expect(screen.getByLabelText("Running")).toBeInTheDocument();
    expect(screen.getByLabelText("Failed")).toBeInTheDocument();
  });

  it("shows the delegate's reasoning apart from its answer", () => {
    render(
      <DelegationPanels
        delegations={[delegation({ thinking: "three sources should do", text: "found three" })]}
      />,
    );

    expect(screen.getByText("three sources should do")).toBeInTheDocument();
    expect(screen.getByTestId("markdown")).toHaveTextContent("found three");
  });
});

describe("DelegationPanels - nesting", () => {
  it("draws a specialist's own delegation inside it, not beside it", () => {
    render(
      <DelegationPanels
        delegations={[
          delegation({ taskId: "t1", subagent: "researcher" }),
          delegation({ taskId: "t2", subagent: "assistant", depth: 1, parentTaskId: "t1" }),
        ]}
      />,
    );

    const parent = screen.getByText("researcher").closest("div.border-l");
    expect(parent).not.toBeNull();
    expect(parent!).toContainElement(screen.getByText("assistant"));
  });

  it("hides a nested delegation with its parent", () => {
    // Folding the parent away has to fold what it delegated away too, or a closed
    // researcher leaves its assistant floating at the top level.
    render(
      <DelegationPanels
        delegations={[
          delegation({ taskId: "t1", subagent: "researcher", status: "completed" }),
          delegation({ taskId: "t2", subagent: "assistant", depth: 1, parentTaskId: "t1" }),
        ]}
      />,
    );

    expect(screen.queryByText("assistant")).toBeNull();
  });
});
