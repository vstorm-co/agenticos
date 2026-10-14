import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ToolCall } from "@/types";

import { TurnDelegations } from "./turn-delegations";

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));

const AGENTS = [
  { id: "a-fin", slug: "finance-analyst", name: "Finance Analyst", avatar_color: 8 },
  { id: "a-sup", slug: "support-desk", name: "Support Desk" },
];

function asked(id: string, slug: string, status: ToolCall["status"] = "completed"): ToolCall {
  return {
    id,
    name: "task",
    args: { subagent_type: slug, description: `Brief for ${slug}` },
    result: `Answer from ${slug}`,
    status,
  };
}

/**
 * Who worked on an answer, under it - the team, not only the work above it.
 * Each delegate opens what it was asked and what it said.
 */
describe("the team under an answer", () => {
  it("says nothing for a turn that asked nobody", () => {
    const { container } = render(
      <TurnDelegations
        toolCalls={[{ id: "x", name: "web_search", args: {}, status: "completed" }]}
        agents={AGENTS}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("names each agent asked, once in the count however often it was asked", () => {
    render(
      <TurnDelegations
        toolCalls={[
          asked("1", "finance-analyst"),
          asked("2", "support-desk"),
          asked("3", "support-desk"),
        ]}
        agents={AGENTS}
      />,
    );

    expect(screen.getByText("Asked 2 agents")).toBeInTheDocument();
    expect(screen.getAllByText("Support Desk")).toHaveLength(2);
    expect(screen.getAllByText("finished")).toHaveLength(3);
  });

  it("opens a delegate at the side, onto its brief and its answer, and closes it", async () => {
    render(<TurnDelegations toolCalls={[asked("1", "finance-analyst")]} agents={AGENTS} />);

    await userEvent.click(screen.getByRole("button", { name: /Finance Analyst/ }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByText("Brief for finance-analyst")).toBeInTheDocument();
    expect(within(sheet).getByText("Answer from finance-analyst")).toBeInTheDocument();

    await userEvent.click(within(sheet).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("moves between the delegates from the faces along the top", async () => {
    render(
      <TurnDelegations
        toolCalls={[asked("1", "finance-analyst"), asked("2", "support-desk")]}
        agents={AGENTS}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Finance Analyst/ }));
    await userEvent.click(screen.getByRole("tab", { name: "Support Desk" }));

    expect(screen.getByRole("tab", { name: "Support Desk" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("Answer from support-desk")).toBeInTheDocument();
  });

  it("says where each delegation stands, a failure as failed", () => {
    render(
      <TurnDelegations
        toolCalls={[
          asked("1", "finance-analyst", "error"),
          asked("2", "support-desk", "running"),
          asked("3", "inline-helper", "awaiting_approval"),
          asked("4", "other-helper", "unfinished"),
        ]}
        agents={AGENTS}
      />,
    );

    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("working…")).toBeInTheDocument();
    expect(screen.getByText("waiting for approval")).toBeInTheDocument();
    expect(screen.getByText("stopped")).toBeInTheDocument();
    // A delegate the reader cannot see still reads as a name.
    expect(screen.getByText("Inline helper")).toBeInTheDocument();
  });

  it("opens a delegation that has no brief or answer to an empty record", async () => {
    render(
      <TurnDelegations
        toolCalls={[
          { id: "1", name: "task", args: { subagent_type: "support-desk" }, status: "running" },
        ]}
        agents={AGENTS}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Support Desk/ }));

    expect(screen.queryByText("Brief")).toBeNull();
    expect(screen.queryByText("Answer")).toBeNull();
  });
});
