import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalDelegate } from "./approval-delegate";
import { apiClient } from "@/lib/api-client";
import type { Permission } from "@/types/permissions";
import type { ToolApproval } from "@/types/runs";

/**
 * Who is asking, on a row in the approvals queue.
 *
 * Driven through the real `usePermissions` against a mocked `/me/permissions`,
 * because whether the delegate's name is a link is a permission decision and a
 * stubbed `can: () => true` would assert nothing about it.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn() } };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** What `/me/permissions` answers with. */
function granting(...permissions: Permission[]) {
  return {
    organization_id: "o1",
    role: "operator",
    is_app_admin: false,
    permissions: permissions.map((permission) => ({ permission, scope: "all" })),
  };
}

function approval(overrides: Partial<ToolApproval> = {}): ToolApproval {
  return {
    id: "ap-1",
    run_id: "run-1",
    agent_id: "agent-parent",
    tool_id: "send_email",
    tool_args: { to: "board@acme.test" },
    subagent_name: null,
    subagent_agent_id: null,
    status: "pending",
    decided_by_user_id: null,
    decided_at: null,
    decided_via: "click" as const,
    note: null,
    created_at: "2026-08-04T09:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.get).mockResolvedValue(granting("agents:view", "approvals:decide"));
});

describe("the delegate on an approval row", () => {
  it("says nothing when the run's own agent asked", () => {
    // `agent_id` is already the run's agent. A label reading "this agent" would be
    // copy invented to fill the space, and it would make every ungated approval in
    // the deployment look like it came from somewhere.
    const { container } = render(<ApprovalDelegate approval={approval()} />, { wrapper });

    expect(container).toBeEmptyDOMElement();
  });

  it("names a published delegate and links to its agent", async () => {
    render(
      <ApprovalDelegate
        approval={approval({ subagent_name: "researcher", subagent_agent_id: "agent-99" })}
      />,
      { wrapper },
    );

    expect(await screen.findByRole("link", { name: "Asked by researcher" })).toHaveAttribute(
      "href",
      "/agents/agent-99",
    );
    expect(screen.queryByText("Inline specialist")).toBeNull();
  });

  it("marks an inline specialist as one, and does not link it", async () => {
    // A specialist is defined inside its parent's spec: no version, no row in
    // `agents`, nothing to open. An unlinked name on its own reads as a published
    // agent whose link somebody forgot, so the row says which it is.
    render(
      <ApprovalDelegate
        approval={approval({ subagent_name: "summariser", subagent_agent_id: null })}
      />,
      { wrapper },
    );

    expect(await screen.findByText("Inline specialist")).toBeVisible();
    expect(screen.getByText("Asked by summariser")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

// The fourth case - a caller without `agents:view`, whose delegate is named but not
// linked - is proved in `runs/delegate-queue.integration.test.tsx`. It needs a
// permission-gated control on screen to show that `/me/permissions` has actually
// answered, and asserting "no link" against a component that renders none while the
// query is still in flight would pass without testing anything.
