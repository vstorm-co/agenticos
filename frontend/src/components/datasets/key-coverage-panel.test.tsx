import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "@/types/agents";
import type { KeyCoverageReport } from "@/types/datasets";
import { KeyCoveragePanel } from "./key-coverage-panel";

const agents = {
  agents: [] as Partial<Agent>[],
  isLoading: false,
  error: null as Error | null,
};
vi.mock("@/hooks/use-eval-runs", () => ({ useEveryAgent: () => agents }));
const coverage = {
  report: null as KeyCoverageReport | null,
  loading: false,
  error: null as Error | null,
  start: vi.fn(),
  starting: false,
};
const asked = vi.fn();
vi.mock("@/hooks/use-key-coverage", () => ({
  useKeyCoverage: (datasetId: string, agentId: string) => {
    asked(datasetId, agentId);
    return coverage;
  },
}));

const WRITER = {
  id: "a1",
  name: "Writer",
  kind: "agent",
  current_version_id: "v1",
  can_edit: true,
};
const READER = { id: "a2", name: "Reader", current_version_id: "v2", can_edit: false };

function report(overrides: Partial<KeyCoverageReport> = {}): KeyCoverageReport {
  return {
    id: "r1",
    agent_id: "a1",
    dataset_id: "d1",
    dataset_version: 3,
    status: "ready",
    items: [
      { key: "Invoice number", verdict: "covered", sources: [], why: null },
      {
        key: "Customer",
        verdict: "unsure",
        sources: [
          { kind: "context", id: null, name: null },
          { kind: "mcp", id: "m1", name: "crm" },
        ],
        why: null,
      },
      { key: "Due date", verdict: "not_covered", sources: [], why: "Nothing names it" },
    ],
    unseen_sources: 0,
    current: true,
    sources_changed: false,
    error: null,
    created_at: "2026-11-20T00:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

async function choose(name: string) {
  render(<KeyCoveragePanel datasetId="d1" />);
  await userEvent.selectOptions(screen.getByLabelText("Agent"), name);
}

beforeEach(() => {
  vi.clearAllMocks();
  agents.agents = [
    WRITER,
    READER,
    { id: "j", name: "Judge", kind: "judge", current_version_id: "x" },
  ];
  agents.isLoading = false;
  agents.error = null;
  coverage.report = null;
  coverage.loading = false;
  coverage.error = null;
  coverage.starting = false;
});

describe("KeyCoveragePanel", () => {
  it("offers published agents people use, and asks nothing until one is chosen", async () => {
    agents.agents = [...agents.agents, { id: "d", name: "Draft", current_version_id: null }];
    render(<KeyCoveragePanel datasetId="d1" />);

    const options = screen.getAllByRole("option").map((option) => option.textContent);
    expect(options).toEqual(["Choose a published agent", "Writer", "Reader"]);
    expect(asked).not.toHaveBeenCalled();

    await userEvent.selectOptions(screen.getByLabelText("Agent"), "Writer");
    expect(asked).toHaveBeenCalledWith("d1", "a1");
    await userEvent.selectOptions(screen.getByLabelText("Agent"), "");
    expect(screen.queryByText("Not checked yet for this agent.")).not.toBeInTheDocument();
  });

  it("says when the agents are loading, failed, or none is published", () => {
    agents.isLoading = true;
    const { unmount } = render(<KeyCoveragePanel datasetId="d1" />);
    expect(screen.queryByLabelText("Agent")).not.toBeInTheDocument();
    unmount();

    agents.isLoading = false;
    agents.error = new Error("offline");
    const failed = render(<KeyCoveragePanel datasetId="d1" />);
    expect(screen.getByText("offline")).toBeInTheDocument();
    failed.unmount();

    agents.error = null;
    agents.agents = [];
    render(<KeyCoveragePanel datasetId="d1" />);
    expect(screen.getByText("No published agent to check")).toBeInTheDocument();
  });

  it("lets an editor ask, and only tells a reader it was not checked", async () => {
    await choose("Writer");
    expect(screen.getByText("Not checked yet for this agent.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check coverage" }));
    expect(coverage.start).toHaveBeenCalled();

    await userEvent.selectOptions(screen.getByLabelText("Agent"), "Reader");
    expect(screen.queryByRole("button", { name: /Check/ })).not.toBeInTheDocument();
    expect(
      screen.getByText("Not checked yet for this agent. Someone who may edit it can check."),
    ).toBeInTheDocument();
  });

  it("lists keys with no source first and leaves a hidden source unnamed", async () => {
    coverage.report = report({ unseen_sources: 2 });
    await choose("Writer");
    expect(screen.queryByText(/Made for an earlier version/)).not.toBeInTheDocument();

    expect(
      screen.getByText("3 keys in version 3: 1 with a source, 1 with none, 1 unsure."),
    ).toBeInTheDocument();
    expect(screen.getByText(/2 sources of this agent were not read/)).toHaveTextContent(
      "so Improve does not use this report",
    );
    const keys = screen.getAllByRole("listitem").map((item) => item.firstChild?.textContent);
    expect(keys).toEqual(["Due dateNo source", "CustomerUnsure", "Invoice numberCovered"]);
    expect(screen.getByText("From: a source you cannot see, crm")).toBeInTheDocument();
    expect(screen.getByText("Nothing names it")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("says a report that could not be read, rather than that none was made", async () => {
    coverage.error = new Error("offline");
    await choose("Writer");

    expect(screen.getByRole("alert")).toHaveTextContent("The coverage report could not be read.");
    expect(screen.queryByText("Not checked yet for this agent.")).not.toBeInTheDocument();
  });

  it("counts unsure keys apart from the ones with a source", async () => {
    coverage.report = report({
      items: [{ key: "Due date", verdict: "unsure", sources: [], why: null }],
    });
    await choose("Writer");

    expect(
      screen.getByText("1 key in version 3: 0 with a source, 0 with none, 1 unsure."),
    ).toBeInTheDocument();
  });

  it("says a report whose sources changed since is out of date", async () => {
    coverage.report = report({ current: false, sources_changed: true });
    await choose("Writer");

    expect(screen.getByText(/Sources changed since this check/)).toBeInTheDocument();
    expect(screen.queryByText(/Made for an earlier version/)).not.toBeInTheDocument();
  });

  it("says a report made for an earlier version is out of date", async () => {
    coverage.report = report({ current: false });
    await choose("Writer");

    expect(screen.getByText(/Made for an earlier version/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
  });

  it("shows a report being judged, one that failed, and one still loading", async () => {
    coverage.report = report({ status: "running", items: [] });
    await choose("Writer");
    expect(screen.getByText("Judging which sources hold each key…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeDisabled();

    coverage.report = report({ status: "failed", items: [], error: "Over budget" });
    await userEvent.selectOptions(screen.getByLabelText("Agent"), "Reader");
    expect(screen.getByText("The coverage could not be judged: Over budget")).toBeInTheDocument();

    coverage.report = report({ status: "failed", items: [], error: null });
    coverage.starting = true;
    await userEvent.selectOptions(screen.getByLabelText("Agent"), "Writer");
    expect(screen.getByRole("button", { name: "Check again" })).toBeDisabled();

    coverage.loading = true;
    await userEvent.selectOptions(screen.getByLabelText("Agent"), "Reader");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
