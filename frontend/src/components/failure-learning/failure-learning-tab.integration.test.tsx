import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FailureLearningTab } from "./failure-learning-tab";
import { apiClient } from "@/lib/api-client";
import { Perm, type Permission } from "@/types/permissions";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** What the caller may do. */
const state = { permissions: [] as Permission[] };

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: state.permissions.map((permission) => ({ permission, scope: "all" })),
      };
    if (path === "/agents/agent-1/failure-learning/patterns")
      return {
        items: [
          {
            agent_id: "agent-1",
            agent_name: "Helper",
            model: "anthropic:claude-sonnet-4-5",
            status: "failed",
            error_class: "ModelHTTPError:400",
            pattern_key: "failed:ModelHTTPError:400",
            count: 4,
            first_seen: "2026-11-03T00:00:00Z",
            last_seen: "2026-11-09T00:00:00Z",
            sample_run_ids: ["run-1"],
            sample_message_ids: [],
            already_tracked: false,
          },
        ],
        total: 1,
        notes: [],
      };
    if (path === "/agents/agent-1/failure-learning/ledger")
      return {
        items: [
          {
            id: "entry-1",
            organization_id: "org-1",
            agent_id: "agent-1",
            scope: "agent",
            model: null,
            pattern_key: "failed:ModelHTTPError:400",
            title: "Bad requests",
            summary: "The agent keeps sending bad requests.",
            evidence: { count: 4 },
            status: "draft",
            created_by_user_id: null,
            eval_case_count: 0,
            proposal_count: 0,
            open_since: null,
            created_at: "2026-11-09T00:00:00Z",
            updated_at: "2026-11-09T00:00:00Z",
          },
        ],
        total: 1,
      };
    if (path === "/agents/agent-1/failure-learning/eval-cases") return { items: [], total: 0 };
    if (path === "/agents/agent-1/failure-learning/proposals") return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.permissions = [Perm.agentsView, Perm.agentsEdit];
});

describe("FailureLearningTab", () => {
  it("shows the agent's patterns and its ledger", async () => {
    serve();
    render(<FailureLearningTab agentId="agent-1" />, { wrapper });

    expect(await screen.findByText("Helper")).toBeInTheDocument();
    expect(screen.getByText("Bad requests")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Track" })).toBeInTheDocument();
  });

  it("shows the rule counts: the draft entry is an open rule, not yet a live one", async () => {
    serve();
    render(<FailureLearningTab agentId="agent-1" />, { wrapper });

    expect(await screen.findByText("Helper")).toBeInTheDocument();
    expect(screen.getByText(/0 applied rules/)).toBeInTheDocument();
    expect(screen.getByText(/1 open entry/)).toBeInTheDocument();
    expect(screen.getByText(/0 resolved entries/)).toBeInTheDocument();
  });

  it("hides the track control from a caller who may only view", async () => {
    state.permissions = [Perm.agentsView];
    serve();
    render(<FailureLearningTab agentId="agent-1" />, { wrapper });

    expect(await screen.findByText("Helper")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Track" })).not.toBeInTheDocument();
  });
});
