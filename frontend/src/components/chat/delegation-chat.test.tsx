import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Delegation } from "@/types";

import { DelegationChat } from "./delegation-chat";

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));

function delegation(overrides: Partial<Delegation> = {}): Delegation {
  return {
    taskId: "t1",
    subagent: "finance-analyst",
    depth: 0,
    mode: "sync",
    prompt: "Where does MRR stand?",
    parentTaskId: null,
    status: "running",
    specialist: null,
    harness: null,
    text: "",
    thinking: "",
    steps: [],
    runId: null,
    costUsd: null,
    inputTokens: null,
    outputTokens: null,
    error: null,
    ...overrides,
  } as Delegation;
}

const AGENTS = [{ id: "a-fin", slug: "finance-analyst", name: "Finance Analyst" }];
const CHIEF = { id: "a-chief", slug: "chief-of-staff", name: "Chief of Staff" };

/** The team talking it through while the turn runs. */
describe("the team at work", () => {
  it("draws a coding harness by its mark and says what it is doing right now", () => {
    render(
      <DelegationChat
        parent={CHIEF}
        agents={AGENTS}
        delegations={[
          delegation({
            subagent: "Claude Code",
            harness: "claude_code",
            steps: [
              { id: "s1", name: "read", ok: true, title: "/workspace/app.py" },
              { id: "s2", name: "command", ok: null, title: "pytest -q" },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getAllByRole("img", { name: "Claude Code" }).length).toBeGreaterThan(0);
    expect(screen.getByText("Running pytest -q")).toBeInTheDocument();
  });

  it("says nothing of a step that names no subject", () => {
    render(
      <DelegationChat
        parent={CHIEF}
        agents={AGENTS}
        delegations={[
          delegation({ steps: [{ id: "s1", name: "search_documents", ok: null, title: null }] }),
        ]}
      />,
    );
    expect(screen.queryByText(/^Running|^Reading/)).toBeNull();
  });

  it("shows what was asked, and the colleague typing while it works", () => {
    const { container } = render(
      <DelegationChat
        parent={CHIEF}
        agents={AGENTS}
        delegations={[
          delegation({
            steps: [
              { id: "s1", name: "search_documents", ok: true, title: null },
              { id: "s2", name: "search_documents", ok: null, title: null },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText("Chief of Staff → Finance Analyst")).toBeInTheDocument();
    expect(screen.getByText("Where does MRR stand?")).toBeInTheDocument();
    expect(screen.getByText(/working… · 2 actions/)).toBeInTheDocument();
    expect(container.querySelector(".typing-dots")).not.toBeNull();
    expect(container.querySelector(".blob-hop")).not.toBeNull();
  });

  it("reads the reply as its first words once they arrive, and stops hopping when done", () => {
    const { container } = render(
      <DelegationChat
        parent={CHIEF}
        agents={AGENTS}
        delegations={[
          delegation({ status: "completed", text: "## Summary\n**MRR is €153k**, up 27%." }),
        ]}
      />,
    );

    expect(screen.getByText("Summary")).toBeInTheDocument();
    expect(container.querySelector(".blob-hop")).toBeNull();
    expect(container.querySelector(".typing-dots")).toBeNull();
  });

  it("names the asker plainly when it does not know which agent it is", () => {
    render(<DelegationChat agents={AGENTS} delegations={[delegation()]} />);

    expect(screen.getByText("Agent → Finance Analyst")).toBeInTheDocument();
  });

  it("opens a reply at the side, with what the colleague did", async () => {
    render(
      <DelegationChat
        parent={CHIEF}
        agents={AGENTS}
        delegations={[
          delegation({
            text: "MRR is €153k.",
            steps: [
              { id: "s1", name: "search_documents", ok: true, title: null },
              { id: "s2", name: "fetch_url", ok: false, title: null },
              { id: "s3", name: "search_documents", ok: null, title: null },
            ],
          }),
        ]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Finance Analyst/ }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByText("Actions")).toBeInTheDocument();
    expect(within(sheet).getByText("Knowledge Base Search")).toBeInTheDocument();
    expect(within(sheet).getByLabelText("Failed")).toBeInTheDocument();

    await userEvent.click(within(sheet).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
