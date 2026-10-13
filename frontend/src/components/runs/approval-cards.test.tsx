import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ApprovalArguments, DecidedApproval, PendingApproval } from "./approval-cards";
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

describe("ApprovalArguments - what a call will be given, as fields", () => {
  it("names each argument in words and shows each kind of value as itself", () => {
    inIntl(
      <li>
        <ApprovalArguments
          args={{
            file_name: "notes.md",
            limit: 3,
            dry_run: false,
            nothing: null,
            filters: { a: 1 },
          }}
        />
      </li>,
    );

    expect(screen.getByText("File Name")).toBeInTheDocument();
    expect(screen.getByText("notes.md")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
    expect(screen.getByText("null")).toBeInTheDocument();
    expect(screen.getByText(/"a": 1/)).toBeInTheDocument();
  });

  it("draws nothing for a call that takes nothing", () => {
    const { container } = inIntl(
      <li>
        <ApprovalArguments args={{}} />
      </li>,
    );
    expect(container.querySelector("dl")).toBeNull();
  });
});

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

describe("DecidedApproval - a line of the record", () => {
  it.each([
    ["approved", "Approved"],
    ["expired", "Expired"],
  ] as const)("marks one %s as %s", (status, label) => {
    inIntl(<DecidedApproval approval={approval({ status })} onOpenRun={vi.fn()} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
