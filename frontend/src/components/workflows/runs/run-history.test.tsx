import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRunRead } from "@/lib/workflows/types";

import { RunHistory } from "./run-history";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const url = vi.hoisted(() => ({ values: {} as Record<string, string | null>, set: vi.fn() }));
const history = vi.hoisted(() => ({
  runs: [] as WorkflowRunRead[],
  total: 0,
  query: vi.fn(),
}));
vi.mock("@/hooks", () => ({
  useUrlState: (key: string) => [
    url.values[key] ?? null,
    (value: string | null) => url.set(key, value),
  ],
  useRunHistory: (query: unknown) => {
    history.query(query);
    return { runs: history.runs, total: history.total, isLoading: false };
  },
  useWorkflows: () => ({ workflows: [{ id: "wf", name: "Lead intake" }] }),
}));

function run(overrides: Partial<WorkflowRunRead> = {}): WorkflowRunRead {
  return {
    id: "r1",
    workflow_id: "wf",
    workflow_version_id: null,
    mode: "test",
    status: "failed",
    triggered_by: "api",
    budget_limit: null,
    spent_cost: 0,
    cost_is_partial: false,
    deadline_at: null,
    paused_reason: null,
    error: null,
    output: null,
    root_run_id: "r1",
    causation_run_id: null,
    retry_of_run_id: null,
    depth: 0,
    started_at: null,
    ended_at: null,
    created_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  url.values = {};
  url.set.mockReset();
  push.mockReset();
  history.runs = [];
  history.total = 0;
});

describe("RunHistory", () => {
  it("lists every workflow's runs with the workflow each belongs to, and opens one", async () => {
    history.runs = [run(), run({ id: "r2", retry_of_run_id: "r1", status: "succeeded" })];
    history.total = 2;
    render(<RunHistory />);

    expect(screen.getAllByText("Lead intake")).toHaveLength(2);
    expect(screen.getByText("retry")).toBeTruthy();
    await userEvent.click(screen.getAllByText("Lead intake")[0] as HTMLElement);
    expect(push).toHaveBeenCalledWith("/workflows/wf/runs/r1");
  });

  it("asks the server for what the address filters on, from the first page when one changes", async () => {
    url.values = { status: "failed", mode: "test", trigger: "webhook", page: "2" };
    render(<RunHistory workflowId="wf" />);

    expect(history.query).toHaveBeenLastCalledWith({
      workflowId: "wf",
      status: "failed",
      mode: "test",
      triggeredBy: "webhook",
      page: 2,
    });
    expect(screen.queryByText("Workflow")).toBeNull();
    expect(screen.getByText("No runs match")).toBeTruthy();

    await userEvent.click(screen.getByRole("combobox", { name: "Status" }));
    await userEvent.click(screen.getByRole("option", { name: "Any status" }));
    expect(url.set).toHaveBeenCalledWith("status", null);
    expect(url.set).toHaveBeenCalledWith("page", null);
  });

  it("narrows to runs started within a window counted back from now", async () => {
    const now = Date.parse("2026-09-30T12:00:00Z");
    vi.spyOn(Date, "now").mockReturnValue(now);
    url.values = { since: "24h" };
    render(<RunHistory workflowId="wf" />);

    expect(history.query).toHaveBeenLastCalledWith(
      expect.objectContaining({ createdAfter: "2026-09-29T12:00:00.000Z" }),
    );
    expect(screen.getByText("No runs match")).toBeTruthy();

    await userEvent.click(screen.getByRole("combobox", { name: "Started by" }));
    expect(screen.getByRole("option", { name: "Another workflow" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "A failed run" })).toBeTruthy();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("combobox", { name: "Started" }));
    await userEvent.click(screen.getByRole("option", { name: "Last 7 days" }));
    expect(url.set).toHaveBeenCalledWith("since", "7d");
    expect(url.set).toHaveBeenCalledWith("page", null);
    vi.restoreAllMocks();
  });

  it("ignores a window the address names that it does not know", () => {
    url.values = { since: "forever" };
    render(<RunHistory workflowId="wf" />);
    expect(history.query).toHaveBeenLastCalledWith(
      expect.objectContaining({ createdAfter: undefined }),
    );
    expect(screen.getByText("No runs yet")).toBeTruthy();
  });

  it("says when a workflow has not run yet", () => {
    render(<RunHistory workflowId="wf" />);
    expect(screen.getByText("No runs yet")).toBeTruthy();
  });

  it("pages through the rest, the first page kept out of the address", async () => {
    history.runs = [run()];
    history.total = 60;
    url.values = { page: "1" };
    render(<RunHistory workflowId="wf" />);

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(url.set).toHaveBeenLastCalledWith("page", "2");
    await userEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(url.set).toHaveBeenLastCalledWith("page", null);
  });
});
