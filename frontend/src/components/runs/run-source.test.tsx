import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentRun, RunOrigin } from "@/types/runs";
import { RunSourceTag } from "./run-source";

function run(overrides: Partial<AgentRun>): AgentRun {
  return { id: "run-1", agent_id: "agent-1", surface: "eval", ...overrides } as AgentRun;
}

function origin(overrides: Partial<RunOrigin>): RunOrigin {
  return { kind: "grader", agent_name: "Judge", ...overrides };
}

describe("RunSourceTag", () => {
  it("says nothing on a conversation", () => {
    const { container } = render(<RunSourceTag run={run({ surface: "web" })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    [
      "an eval answer",
      run({
        eval_case: {
          eval_run_id: "eval-1",
          agent_id: "agent-1",
          case_id: "case-1",
          dataset_name: "Refunds",
          case_input: "Can I return it?",
          graded: false,
        },
      }),
      "Eval",
      "Open the eval run",
      "/agents/agent-1/evals/eval-1",
    ],
    [
      "an Improve session",
      run({
        origin: origin({ kind: "improve", agent_id: "agent-1", improvement_id: "session-1" }),
      }),
      "Improve",
      "Open the Improve session",
      "/agents/agent-1/improve/session-1",
    ],
    [
      "a drafted topic",
      run({
        origin: origin({ kind: "knowledge_gaps", knowledge_base_id: "kb-1", topic_id: "topic-1" }),
      }),
      "Knowledge gaps",
      "Open the topic",
      "/rag/kb-1?tab=gaps&topic=topic-1",
    ],
    [
      "a knowledge base's answers read",
      run({ origin: origin({ kind: "knowledge_gaps", knowledge_base_id: "kb-1" }) }),
      "Knowledge gaps",
      "Open the knowledge gaps",
      "/rag/kb-1?tab=gaps",
    ],
    [
      "cases written",
      run({ origin: origin({ kind: "test_questions", dataset_id: "ds-1" }) }),
      "Test questions",
      "Open the dataset",
      "/datasets/ds-1?tab=generated",
    ],
  ])("names %s and links to where it is read", (_name, row, label, link, href) => {
    render(<RunSourceTag run={row} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: link })).toHaveAttribute("href", href);
  });

  it("names a grader with nothing it may link to, and keeps a link's click off the row", () => {
    const onRow = vi.fn();
    const { rerender } = render(<RunSourceTag run={run({ origin: origin({}) })} />);
    expect(screen.getByText("Grader")).toHaveAttribute("title", "Judge");
    expect(screen.queryByRole("link")).toBeNull();

    rerender(
      <RunSourceTag run={run({ origin: origin({ kind: "improve", agent_id: "agent-1" }) })} />,
    );
    document.body.addEventListener("click", onRow);
    fireEvent.click(screen.getByRole("link", { name: "Open the agent" }));
    document.body.removeEventListener("click", onRow);
    expect(onRow).not.toHaveBeenCalled();
  });
});
