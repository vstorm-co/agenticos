import { fireEvent, render, screen } from "@testing-library/react";
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
vi.mock("@/lib/mobile/haptics", () => ({ haptic: vi.fn() }));

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

describe("PendingApproval - decided with a swipe on a phone", () => {
  it("approves on a swipe right and rejects on a swipe left", () => {
    const onDecide = vi.fn();
    inIntl(
      <PendingApproval
        approval={approval()}
        deciding={false}
        onDecide={onDecide}
        onOpenRun={vi.fn()}
      />,
    );
    const row = screen.getByText("MEMORY.md").closest("[class*=touch-pan-y]")!;
    for (const to of [200, -200]) {
      fireEvent.pointerDown(row, { pointerId: 1, pointerType: "touch", clientX: 0, clientY: 0 });
      fireEvent.pointerMove(row, { pointerId: 1, pointerType: "touch", clientX: to, clientY: 0 });
      fireEvent.pointerUp(row, { pointerId: 1, pointerType: "touch" });
    }

    expect(onDecide.mock.calls).toEqual([[true], [false]]);
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

  it("names the chat account, unverified, instead of the publisher's email", () => {
    inIntl(
      <PendingApproval
        approval={approval({
          triggered_by_email: null,
          asked_in_chat: { platform: "slack", name: "Ana", bot_name: "Support" },
        })}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Asked in Slack by Ana (unverified), through Support"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^For /)).toBeNull();
  });

  it("leaves the bot out when its binding is gone", () => {
    inIntl(
      <PendingApproval
        approval={approval({
          triggered_by_email: null,
          asked_in_chat: { platform: "telegram", name: "@ana", bot_name: null },
        })}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={vi.fn()}
      />,
    );
    expect(screen.getByText("Asked in Telegram by @ana (unverified)")).toBeInTheDocument();
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

  it("names the chat account, unverified, instead of the publisher's email", () => {
    inIntl(
      <DecidedApproval
        approval={approval({
          status: "approved",
          triggered_by_email: null,
          asked_in_chat: { platform: "slack", name: "Ana", bot_name: "Support" },
        })}
        onOpenRun={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Asked in Slack by Ana (unverified), through Support"),
    ).toBeInTheDocument();
  });

  it("still says who it was for when a member asked", () => {
    inIntl(
      <DecidedApproval
        approval={approval({ status: "approved", triggered_by_email: "ada@acme.test" })}
        onOpenRun={vi.fn()}
      />,
    );
    expect(screen.getByText("For ada@acme.test")).toBeInTheDocument();
    expect(screen.queryByText(/Asked in/)).toBeNull();
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

describe("PendingApproval - a fact somebody's run would share", () => {
  const share = {
    tool_id: "share_memory",
    capability_tool_id: "share_memory",
    tool_args: { claim_id: "c-1", to: "organization" },
  };

  it("leads with the fact and who would read it", () => {
    inIntl(
      <PendingApproval
        approval={approval({
          ...share,
          context: { claim: "The Acme renewal is due in March", audience: "organization" },
        })}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Share with the whole organization: “The Acme renewal is due in March”"),
    ).toBeInTheDocument();
  });

  it("says why the fact is missing for a reader who may not see the run", () => {
    inIntl(
      <PendingApproval
        approval={approval({
          ...share,
          context: { audience: "project" },
          content_hidden: true,
        })}
        deciding={false}
        onDecide={vi.fn()}
        onOpenRun={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        "What this call quotes from its run is shown only to people who can see that run.",
      ),
    ).toBeInTheDocument();
  });
});

it("offers only Reject on a call that always asks when the reader cannot see what it quotes", async () => {
  const onDecide = vi.fn();
  inIntl(
    <PendingApproval
      approval={approval({
        tool_id: "share_memory",
        capability_tool_id: "share_memory",
        tool_args: { claim_id: "c-1", to: "organization" },
        context: { audience: "organization" },
        content_hidden: true,
        always_asks: true,
      })}
      deciding={false}
      onDecide={onDecide}
      onOpenRun={vi.fn()}
    />,
  );

  expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
  expect(
    screen.getByText("Only somebody who can see the run can approve this. You can reject it."),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Reject/ }));
  expect(onDecide).toHaveBeenCalledWith(false);
});

it("words a correction by the fact before and after it", () => {
  inIntl(
    <PendingApproval
      approval={approval({
        tool_id: "correct_memory",
        capability_tool_id: "correct_memory",
        tool_args: { claim_id: "c-1", statement: "Office closes at five" },
        context: { before: "Office closes at six", after: "Office closes at five" },
      })}
      deciding={false}
      onDecide={vi.fn()}
      onOpenRun={vi.fn()}
    />,
  );

  expect(
    screen.getByText("Correct “Office closes at six” to “Office closes at five”"),
  ).toBeInTheDocument();
});
