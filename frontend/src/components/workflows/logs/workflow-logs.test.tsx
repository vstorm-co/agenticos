import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { LogQuery, WorkflowLogEntry } from "@/lib/workflows/types";

import { WorkflowLogs } from "./workflow-logs";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const url = vi.hoisted(() => ({ values: {} as Record<string, string | null>, set: vi.fn() }));
const logs = vi.hoisted(() => ({
  entries: [] as WorkflowLogEntry[],
  total: 0,
  error: null as Error | null,
  loading: false,
  refetch: vi.fn(),
  query: vi.fn(),
}));
const HTTP = {
  id: "http.request",
  version: 1,
  name: "HTTP",
  ports: [
    { id: "in", label: "in", kind: "input", schema: null },
    { id: "out", label: "Done", kind: "output", schema: null },
  ],
};
const logging = (id: string, label: string, definition = "http.request") => ({
  id,
  definition_id: definition,
  definition_version: 1,
  label,
  quick_log: { message: "x", outputs: null },
});
const graphs = vi.hoisted(() => ({
  workflow: null as unknown,
  live: null as unknown,
  catalog: [] as unknown[],
}));
vi.mock("@/hooks", () => ({
  useUrlState: (key: string) => [
    url.values[key] ?? null,
    (value: string | null) => url.set(key, value),
  ],
  useWorkflowLogs: (query: LogQuery) => {
    logs.query(query);
    return {
      entries: logs.entries,
      total: logs.total,
      isLoading: logs.loading,
      error: logs.error,
      refetch: logs.refetch,
    };
  },
  useWorkflow: () => ({ workflow: graphs.workflow }),
  useWorkflowVersion: () => ({
    version: graphs.live === null ? undefined : { graph: graphs.live },
  }),
  useNodeCatalog: () => ({ nodes: graphs.catalog }),
}));

function entry(overrides: Partial<WorkflowLogEntry> = {}): WorkflowLogEntry {
  return {
    id: "e1",
    workflow_id: "wf",
    run_id: "r1",
    node_instance_id: "n1",
    step_label: "Fetch lead",
    outcome: "out",
    status: "succeeded",
    message: "Fetched 3 leads",
    is_test: false,
    is_pinned: false,
    created_at: "2026-10-28T09:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  graphs.workflow = {
    current_version_id: null,
    draft_graph: {
      nodes: [
        logging("n1", "Fetch lead"),
        { id: "n2", definition_id: "http.request", definition_version: 1, label: "Silent" },
      ],
    },
  };
  graphs.live = null;
  graphs.catalog = [HTTP];
  logs.loading = false;
  url.values = {};
  url.set.mockReset();
  push.mockReset();
  logs.entries = [];
  logs.total = 0;
  logs.error = null;
  logs.refetch.mockReset();
  logs.query.mockReset();
});

describe("WorkflowLogs", () => {
  it("lists the lines with their step, outcome and message, and opens the run that wrote one", async () => {
    logs.entries = [
      entry(),
      entry({ id: "e2", run_id: "r2", outcome: "error", message: "Timed out", is_test: true }),
    ];
    logs.total = 2;
    render(<WorkflowLogs workflowId="wf" />);

    expect(screen.getByText("Fetched 3 leads")).toBeTruthy();
    expect(screen.getByText("2 lines")).toBeTruthy();
    expect(screen.getByText("test")).toBeTruthy();
    await userEvent.click(screen.getByText("Timed out"));
    expect(push).toHaveBeenCalledWith("/workflows/wf/runs/r2");
  });

  it("asks for the first page with test runs left out until it is told otherwise", () => {
    render(<WorkflowLogs workflowId="wf" />);
    expect(logs.query).toHaveBeenLastCalledWith({
      workflowId: "wf",
      nodeInstanceId: undefined,
      outcome: undefined,
      from: undefined,
      q: undefined,
      includeTest: false,
      page: 0,
    });
  });

  it("sends what the address filters on, and goes back to the first page when one changes", async () => {
    url.values = { step: "n1", outcome: "error", test: "1", page: "2" };
    render(<WorkflowLogs workflowId="wf" />);

    expect(logs.query).toHaveBeenLastCalledWith(
      expect.objectContaining({
        nodeInstanceId: "n1",
        outcome: "error",
        includeTest: true,
        page: 2,
      }),
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    await userEvent.click(await screen.findByRole("option", { name: "Done" }));
    expect(url.set).toHaveBeenCalledWith("outcome", "out");
    expect(url.set).toHaveBeenCalledWith("page", null);
  });

  it("offers only the steps that log, and the outcomes they leave by", async () => {
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("combobox", { name: "Step" }));
    expect(await screen.findByRole("option", { name: "Fetch lead" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Silent" })).toBeNull();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    expect(await screen.findByRole("option", { name: "error" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Done" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "in" })).toBeNull();
  });

  it("narrows to a recent window from the time filter, counted back from the choice", async () => {
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("combobox", { name: "Written" }));
    await userEvent.click(await screen.findByRole("option", { name: "Last 24 hours" }));
    expect(url.set).toHaveBeenCalledWith("since", "24h");
    expect(url.set).toHaveBeenCalledWith("page", null);
  });

  it("marks a line a pinned step wrote", () => {
    logs.entries = [entry({ is_pinned: true })];
    logs.total = 1;
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByText("pinned")).toBeTruthy();
  });

  it("turns test runs on from the switch", async () => {
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("switch", { name: "Include test runs" }));
    expect(url.set).toHaveBeenCalledWith("test", "1");
  });

  it("searches the message once typing pauses", async () => {
    vi.useFakeTimers();
    try {
      render(<WorkflowLogs workflowId="wf" />);
      const box = screen.getByPlaceholderText("Search messages");
      await act(async () => {
        fireEvent.change(box, { target: { value: " timeout " } });
        await vi.advanceTimersByTimeAsync(400);
      });
      expect(logs.query).toHaveBeenLastCalledWith(expect.objectContaining({ q: "timeout" }));
    } finally {
      vi.useRealTimers();
    }
  });

  it("says nothing is logged yet when there is no filter, and no match when there is one", () => {
    const { unmount } = render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByText("Nothing logged yet")).toBeTruthy();
    unmount();

    url.values = { outcome: "error" };
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByText("No lines match")).toBeTruthy();
  });

  it("shows a failed request as a failure with a retry, never as an empty log", async () => {
    logs.error = new Error("boom");
    render(<WorkflowLogs workflowId="wf" />);

    expect(screen.getByText("The log could not be read")).toBeTruthy();
    expect(screen.queryByText("Nothing logged yet")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(logs.refetch).toHaveBeenCalled();
  });

  it("offers a step that is still live though the draft no longer has it", async () => {
    graphs.workflow = {
      current_version_id: "v1",
      draft_graph: { nodes: [logging("n1", "Fetch lead")] },
    };
    graphs.live = { nodes: [logging("n1", "Fetch lead"), logging("n9", "Old step")] };
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("combobox", { name: "Step" }));
    expect(await screen.findByRole("option", { name: "Fetch lead" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Old step" })).toBeTruthy();
  });

  it("keeps a step and an outcome the address names as options when no graph has them", () => {
    url.values = { step: "gone", outcome: "left" };
    logs.entries = [entry({ node_instance_id: "gone", step_label: "Removed step" })];
    logs.total = 1;
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByRole("combobox", { name: "Step" })).toHaveTextContent("Removed step");
    expect(screen.getByRole("combobox", { name: "Outcome" })).toHaveTextContent("left");
  });

  it("names a missing step by its id when no line says what it was called", () => {
    url.values = { step: "gone-id" };
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByRole("combobox", { name: "Step" })).toHaveTextContent("gone-id");
  });

  it("reads an outcome as its port's label in the cells, and as the id without one", () => {
    logs.entries = [entry(), entry({ id: "e2", outcome: "error", message: "bad" })];
    logs.total = 2;
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByText("Done")).toBeTruthy();
    expect(screen.getByText("error")).toBeTruthy();
  });

  it("writes the time down to the second", () => {
    logs.entries = [entry({ created_at: "2026-10-28T09:00:07Z" })];
    logs.total = 1;
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByText(/:07/)).toBeTruthy();
  });

  it("filters by a run from a text field, with no list of runs to pick from", () => {
    url.values = { run: "3f2a-91" };
    render(<WorkflowLogs workflowId="wf" />);

    expect(screen.getByPlaceholderText("Run: paste an id or its start")).toHaveValue("3f2a-91");
    expect(logs.query).toHaveBeenLastCalledWith(expect.objectContaining({ run: "3f2a-91" }));
    expect(screen.queryByRole("combobox", { name: /run/i })).toBeNull();
  });

  it("keeps the run in the address as it is typed, without spaces, and asks once typing pauses", async () => {
    vi.useFakeTimers();
    try {
      const { rerender } = render(<WorkflowLogs workflowId="wf" />);
      const box = screen.getByPlaceholderText("Run: paste an id or its start");
      fireEvent.change(box, { target: { value: " 3f2a-91 \n" } });
      expect(url.set).toHaveBeenCalledWith("run", "3f2a-91");
      expect(url.set).toHaveBeenCalledWith("page", null);
      expect(logs.query).toHaveBeenLastCalledWith(expect.objectContaining({ run: undefined }));

      url.values = { run: "3f2a-91" };
      rerender(<WorkflowLogs workflowId="wf" />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(400);
      });
      expect(logs.query).toHaveBeenLastCalledWith(expect.objectContaining({ run: "3f2a-91" }));
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears the run with its x", async () => {
    url.values = { run: "3f2a-91" };
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("button", { name: "Clear the run filter" }));
    expect(url.set).toHaveBeenCalledWith("run", null);
  });

  it("applies a row's action and the x at once, and only typing waits", async () => {
    vi.useFakeTimers();
    try {
      logs.entries = [entry({ run_id: "r2" })];
      logs.total = 1;
      url.values = { run: "r1" };
      const { rerender } = render(<WorkflowLogs workflowId="wf" />);
      fireEvent.click(screen.getByRole("button", { name: "Show only this run" }));
      url.values = { run: "r2" };
      rerender(<WorkflowLogs workflowId="wf" />);
      expect(logs.query).toHaveBeenLastCalledWith(expect.objectContaining({ run: "r2" }));

      fireEvent.click(screen.getByRole("button", { name: "Clear the run filter" }));
      url.values = {};
      rerender(<WorkflowLogs workflowId="wf" />);
      expect(logs.query).toHaveBeenLastCalledWith(expect.objectContaining({ run: undefined }));

      fireEvent.change(screen.getByPlaceholderText("Run: paste an id or its start"), {
        target: { value: "3f2a" },
      });
      url.values = { run: "3f2a" };
      rerender(<WorkflowLogs workflowId="wf" />);
      expect(logs.query).not.toHaveBeenLastCalledWith(expect.objectContaining({ run: "3f2a" }));
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not bring a cleared run back when typing starts right after the x", async () => {
    vi.useFakeTimers();
    try {
      logs.entries = [entry({ run_id: "r2" })];
      logs.total = 1;
      const { rerender } = render(<WorkflowLogs workflowId="wf" />);
      fireEvent.click(screen.getByRole("button", { name: "Show only this run" }));
      url.values = { run: "r2" };
      rerender(<WorkflowLogs workflowId="wf" />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10);
      });
      fireEvent.click(screen.getByRole("button", { name: "Clear the run filter" }));
      url.values = {};
      rerender(<WorkflowLogs workflowId="wf" />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10);
      });
      fireEvent.change(screen.getByPlaceholderText("Run: paste an id or its start"), {
        target: { value: "3f2a" },
      });
      url.values = { run: "3f2a" };
      rerender(<WorkflowLogs workflowId="wf" />);
      expect(logs.query).toHaveBeenLastCalledWith(expect.objectContaining({ run: undefined }));
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers no x while the run field is empty", () => {
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.queryByRole("button", { name: "Clear the run filter" })).toBeNull();
  });

  it("fills the run field from a row's action without opening that run", async () => {
    logs.entries = [entry({ run_id: "r2" })];
    logs.total = 1;
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("button", { name: "Show only this run" }));
    expect(url.set).toHaveBeenCalledWith("run", "r2");
    expect(url.set).toHaveBeenCalledWith("page", null);
    expect(push).not.toHaveBeenCalled();
  });

  it("counts a run in the address as a filter when nothing matches", () => {
    url.values = { run: "3f2a" };
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByText("No lines match")).toBeTruthy();
  });

  it("shows the message the server gave for a refused run on the field, not an empty list", () => {
    url.values = { run: "3f" };
    logs.error = new ApiError(422, "Validation error", {
      error: {
        code: "VALIDATION_ERROR",
        message: "Validation error",
        details: {
          fields: [{ field: "run", message: "A run id, or its first 4 or more characters" }],
        },
      },
    });
    render(<WorkflowLogs workflowId="wf" />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "A run id, or its first 4 or more characters",
    );
    expect(screen.getByPlaceholderText("Run: paste an id or its start")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.queryByText("No lines match")).toBeNull();
    expect(screen.queryByText("The log could not be read")).toBeNull();
  });

  it("limits the search to what the route accepts", () => {
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByPlaceholderText("Search messages")).toHaveAttribute("maxlength", "200");
  });

  it("offers every step by its definition when the catalog does not know it", async () => {
    graphs.workflow = {
      current_version_id: null,
      draft_graph: { nodes: [logging("n5", "", "mystery.node")] },
    };
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("combobox", { name: "Step" }));
    expect(await screen.findByRole("option", { name: /mystery\.node/ })).toBeTruthy();
  });

  it("offers only an error outcome while the workflow has no draft graph", async () => {
    graphs.workflow = { current_version_id: null, draft_graph: null };
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    expect(await screen.findByRole("option", { name: "error" })).toBeTruthy();
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });

  it("reads no workflow as no steps", () => {
    graphs.workflow = null;
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.getByRole("combobox", { name: "Step" })).toBeTruthy();
  });

  it("sends the start of the window the time filter reaches back to", () => {
    url.values = { since: "1h" };
    render(<WorkflowLogs workflowId="wf" />);
    const { from } = logs.query.mock.lastCall?.[0] as LogQuery;
    expect(Date.now() - new Date(from as string).getTime()).toBeLessThan(5_000 + 3_600_000);
    expect(Date.now() - new Date(from as string).getTime()).toBeGreaterThanOrEqual(3_600_000);
  });

  it("clears a filter when its Any choice is made again", async () => {
    url.values = { outcome: "out" };
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    await userEvent.click(await screen.findByRole("option", { name: "Any outcome" }));
    expect(url.set).toHaveBeenCalledWith("outcome", null);
  });

  it("turns test runs off from the switch when they are on", async () => {
    url.values = { test: "1" };
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("switch", { name: "Include test runs" }));
    expect(url.set).toHaveBeenCalledWith("test", null);
  });

  it("moves between pages, the first page leaving the address clean", async () => {
    url.values = { page: "1" };
    logs.entries = [entry()];
    logs.total = 120;
    render(<WorkflowLogs workflowId="wf" />);
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(url.set).toHaveBeenCalledWith("page", "2");
    await userEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(url.set).toHaveBeenCalledWith("page", null);
  });

  it("reads a page the address garbles as the first", () => {
    url.values = { page: "abc" };
    render(<WorkflowLogs workflowId="wf" />);
    expect(logs.query).toHaveBeenLastCalledWith(expect.objectContaining({ page: 0 }));
  });

  it("counts nothing while loading or failing", () => {
    logs.loading = true;
    const { unmount } = render(<WorkflowLogs workflowId="wf" />);
    expect(screen.queryByText("0 lines")).toBeNull();
    unmount();

    logs.loading = false;
    logs.error = new Error("boom");
    logs.total = 0;
    render(<WorkflowLogs workflowId="wf" />);
    expect(screen.queryByText(/line/)).toBeNull();
  });
});
