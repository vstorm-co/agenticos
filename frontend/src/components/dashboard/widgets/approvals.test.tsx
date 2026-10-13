import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import type { ToolApproval } from "@/types/runs";
import { ApprovalsWidget } from "./approvals";

const useApprovalsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useApprovals: (...args: unknown[]) => useApprovalsMock(...args),
  useAgents: () => ({
    agents: [{ id: "a1", name: "Architect", slug: "architect", has_avatar: false }],
  }),
}));
vi.mock("@/stores", () => ({ useArchitectMarkStore: () => false }));

const PERIOD: Period = { preset: "30d", from: "2026-09-14", to: "2026-10-13" };

function approval(overrides: Partial<ToolApproval> = {}): ToolApproval {
  return {
    id: "ap1",
    run_id: "r1",
    agent_id: "a1",
    agent_name: "Architect",
    tool_id: "write_memory",
    tool_args: {},
    triggered_by_email: "kacper@example.com",
    subagent_name: null,
    subagent_agent_id: null,
    status: "pending",
    decided_by_user_id: null,
    decided_at: null,
    decided_via: "click",
    note: null,
    created_at: new Date(Date.now() - 3_600_000).toISOString(),
    ...overrides,
  };
}

function renderWidget(state: Record<string, unknown>) {
  useApprovalsMock.mockReturnValue({
    approvals: [],
    total: 0,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...state,
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <ApprovalsWidget title="Waiting on a decision" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useApprovalsMock.mockReset());

describe("the approvals card", () => {
  it("names who asks and for what, in words, with the agent's face", () => {
    renderWidget({ approvals: [approval()], total: 1 });

    const row = screen.getByRole("listitem");
    expect(row).toHaveTextContent("Architect · Save to memory");
    expect(row).toHaveTextContent("for kacper@example.com · waiting");
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      "/runs?tab=approvals",
    );
  });

  it("names the delegate asking, an unnamed run's agent, and a tool nobody catalogued", () => {
    renderWidget({
      approvals: [
        approval({ id: "ap1", subagent_name: "Researcher", tool_id: "create_issue" }),
        approval({ id: "ap2", agent_name: null, triggered_by_email: null }),
        approval({ id: "ap3", created_at: undefined }),
      ],
      total: 5,
    });

    const [delegated, anonymous, undated] = screen.getAllByRole("listitem");
    expect(delegated).toHaveTextContent("Researcher · Create issue");
    expect(anonymous).toHaveTextContent("An agent · Save to memory");
    expect(anonymous).toHaveTextContent(/^.*waiting/);
    expect(undated).not.toHaveTextContent("waiting");
    expect(screen.getByText("2 more in the queue")).toBeVisible();
  });

  it("says nothing is waiting, offers a retry, and holds a skeleton while loading", async () => {
    renderWidget({});
    expect(screen.getByText("Nothing waiting")).toBeVisible();
  });

  it("offers a retry when the queue cannot be read", async () => {
    const refetch = vi.fn();
    renderWidget({ error: new Error("502"), refetch });
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("holds a skeleton while the queue loads", () => {
    renderWidget({ isLoading: true });
    expect(screen.queryByRole("listitem")).toBeNull();
  });
});
