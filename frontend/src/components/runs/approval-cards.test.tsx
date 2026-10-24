import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { DecidedApproval, PendingApproval } from "./approval-cards";
import type { ToolApproval } from "@/types/runs";

vi.mock("@/components/dashboard/agent-face", () => ({
  AgentFace: ({ agentId }: { agentId: string }) => <span>{`face ${agentId}`}</span>,
}));
vi.mock("@/components/runs/approval-delegate", () => ({ ApprovalDelegate: () => null }));

function approval(overrides: Partial<ToolApproval> = {}): ToolApproval {
  return {
    id: "ap-1",
    run_id: "run-1",
    agent_id: "agent-1",
    agent_name: "Architect",
    tool_id: "write_memory",
    tool_args: { name: "MEMORY.md" },
    subagent_name: null,
    subagent_agent_id: null,
    status: "pending",
    decided_by_user_id: null,
    decided_at: null,
    decided_via: "click",
    note: null,
    created_at: null,
    ...overrides,
  } as ToolApproval;
}

function inIntl(node: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ul>{node}</ul>
    </NextIntlClientProvider>,
  );
}

describe("PendingApproval - a request a person reads", () => {
  it("says who wants to do what, and opens the run it belongs to", async () => {
    const onOpenRun = vi.fn();
    inIntl(
      <PendingApproval
        approval={approval()}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={onOpenRun}
      />,
    );

    expect(screen.getByText("Architect")).toBeInTheDocument();
    // The catalog's words, read inside the sentence, and the telling argument.
    expect(screen.getByText("save to memory")).toBeInTheDocument();
    expect(screen.getByText("MEMORY.md")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Open the run/ }));

    expect(onOpenRun).toHaveBeenCalled();
  });

  it("names a delegate over the run's own agent, and an unnamed one as an agent", () => {
    inIntl(
      <>
        <PendingApproval
          approval={approval({ id: "a", subagent_name: "researcher" })}
          deciding={false}
          onDecide={vi.fn()}
          onOpenRun={vi.fn()}
        />
        <PendingApproval
          approval={approval({ id: "b", agent_name: null })}
          deciding={false}
          onDecide={vi.fn()}
          onOpenRun={vi.fn()}
        />
      </>,
    );

    expect(screen.getByText("researcher")).toBeInTheDocument();
    expect(screen.getByText("An agent")).toBeInTheDocument();
  });
});

describe("PendingApproval - a call from an MCP server", () => {
  it("reads as the service and its action, with the arguments folded", async () => {
    inIntl(
      <PendingApproval
        approval={approval({
          agent_name: "AgenticOS",
          tool_id: "notion_notion-search",
          tool_args: { query: "what's new", page_url: "" },
        })}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={vi.fn()}
      />,
    );

    expect(screen.getByText("search in Notion")).toBeInTheDocument();
    expect(screen.getByText("what's new")).toBeInTheDocument();
    expect(screen.queryByText("Page Url")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByText("Query")).toBeInTheDocument();
    expect(screen.queryByText("Page Url")).toBeNull();
  });

  it("says whom the call is for", () => {
    inIntl(
      <PendingApproval
        approval={approval({ triggered_by_email: "ada@acme.test" } as Partial<ToolApproval>)}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={vi.fn()}
      />,
    );
    expect(screen.getByText("For ada@acme.test")).toBeInTheDocument();
  });

  it("says which account the call acts as, where it names one", () => {
    inIntl(
      <PendingApproval
        approval={approval({ tool_id: "gmail_send", account: "Work" })}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={vi.fn()}
      />,
    );
    expect(screen.getByText("Account: Work")).toBeInTheDocument();
  });

  it("has no telling line for a call with nothing to say", () => {
    inIntl(
      <PendingApproval
        approval={approval({ tool_args: {} })}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={vi.fn()}
      />,
    );
    expect(screen.queryByText("MEMORY.md")).toBeNull();
  });
});

describe("DecidedApproval - a line of the record", () => {
  it.each([
    ["approved", "Approved"],
    ["expired", "Expired"],
  ] as const)("marks one %s as %s", (status, label) => {
    inIntl(<DecidedApproval approval={approval({ status })} onOpenRun={vi.fn()} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("keeps the account on the record", () => {
    inIntl(
      <DecidedApproval
        approval={approval({ status: "rejected", account: "Work" })}
        onOpenRun={vi.fn()}
      />,
    );
    expect(screen.getByText("Account: Work")).toBeInTheDocument();
  });
});
