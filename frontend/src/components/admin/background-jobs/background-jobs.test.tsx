import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobCounts } from "./job-counts";
import { JobsTable } from "./jobs-table";
import { PausedKinds } from "./paused-kinds";
import { WorkersAndSchedules, interval } from "./workers-and-schedules";
import type { BackgroundJob } from "@/types/background-jobs";

const retry = vi.fn();
const cancel = vi.fn();
const fetchNextPage = vi.fn();
let jobsState: Record<string, unknown> = {};

vi.mock("@/hooks/use-background-jobs", () => ({
  useBackgroundJobs: () => jobsState,
  useBackgroundJobActions: () => ({ retry: { mutate: retry }, cancel: { mutate: cancel } }),
}));

function job(overrides: Partial<BackgroundJob>): BackgroundJob {
  return {
    id: "j",
    kind: "ingest-document",
    pool: "ingest",
    status: "queued",
    priority: 0,
    attempts: 0,
    max_attempts: 2,
    organization_id: null,
    schedule_name: null,
    worker_id: null,
    last_error: null,
    run_after: new Date().toISOString(),
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  jobsState = {
    data: { pages: [{ items: [] }] },
    isPending: false,
    error: null,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage,
  };
});

describe("the counts", () => {
  const counts = { queued: 3, running: 1, dead: 2, succeeded: 40, cancelled: 0 };

  it("shows every state and chooses one, then lets it go", () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <JobCounts counts={counts} selected={undefined} onSelect={onSelect} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Dead/ }));
    expect(onSelect).toHaveBeenLastCalledWith("dead");

    rerender(<JobCounts counts={counts} selected="dead" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /Dead/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /Dead/ }));
    expect(onSelect).toHaveBeenLastCalledWith(undefined);
  });
});

describe("the paused kinds", () => {
  const paused = {
    kind: "ingest-document",
    organization_id: null,
    organization_name: null,
    consecutive_deaths: 5,
    lease_lost: 0,
    paused_at: "2026-10-19T10:00:00Z",
    paused_reason: "5 jobs of this kind in a row ended with their worker process dead",
  };

  it("say nothing while nothing is paused", () => {
    const { container } = render(
      <PausedKinds kinds={[{ ...paused, paused_at: null }]} onResume={vi.fn()} resuming={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("name the kind and why, and resume it", () => {
    const onResume = vi.fn();
    render(<PausedKinds kinds={[paused]} onResume={onResume} resuming={null} />);

    expect(screen.getByText("A kind of job is paused")).toBeInTheDocument();
    expect(screen.getByText(paused.paused_reason)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(onResume).toHaveBeenCalledWith(paused);
    expect(screen.getByText("Paused for every organization")).toBeInTheDocument();
  });

  it("say which organization a kind is paused for, and resume that pause alone", () => {
    const onResume = vi.fn();
    const forAcme = { ...paused, organization_id: "o-1", organization_name: "Acme" };
    render(<PausedKinds kinds={[paused, forAcme]} onResume={onResume} resuming={forAcme} />);

    expect(screen.getByText("Paused for Acme")).toBeInTheDocument();
    const [everywhere, acme] = screen.getAllByRole("button", { name: "Resume" });
    // Resuming Acme's pause holds its button, not the deployment-wide one.
    expect(acme).toBeDisabled();
    expect(everywhere).toBeEnabled();
    fireEvent.click(everywhere!);
    expect(onResume).toHaveBeenCalledWith(paused);
  });

  it("hold the button while that kind is resuming", () => {
    render(
      <PausedKinds
        kinds={[{ ...paused, paused_reason: null }]}
        onResume={vi.fn()}
        resuming={{ kind: "ingest-document", organization_id: null }}
      />,
    );
    expect(screen.getByRole("button", { name: "Resume" })).toBeDisabled();
  });
});

describe("the jobs table", () => {
  it("offers retry on a dead job and cancel on a queued one, and shows why a job died", () => {
    const dead = job({ id: "d", status: "dead", attempts: 2, last_error: "killed by SIGKILL" });
    const queued = job({ id: "q", status: "queued", kind: "sync-source" });
    const running = job({ id: "r", status: "running", kind: "fire-trigger", pool: "agent" });
    jobsState = { ...jobsState, data: { pages: [{ items: [dead, queued, running] }] } };
    render(<JobsTable status={undefined} pool={undefined} onPool={vi.fn()} />);

    expect(screen.getByText("killed by SIGKILL")).toBeInTheDocument();
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledWith(dead);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(cancel).toHaveBeenCalledWith(queued);
    expect(screen.getAllByRole("button", { name: /Retry|Cancel/ })).toHaveLength(2);
  });

  it("narrows to one pool, and back to all of them", async () => {
    const onPool = vi.fn();
    const { rerender } = render(<JobsTable status={undefined} pool={undefined} onPool={onPool} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by pool" }));
    await userEvent.click(screen.getByRole("option", { name: "Ingestion" }));
    expect(onPool).toHaveBeenLastCalledWith("ingest");

    rerender(<JobsTable status={undefined} pool="ingest" onPool={onPool} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by pool" }));
    await userEvent.click(screen.getByRole("option", { name: "All pools" }));
    expect(onPool).toHaveBeenLastCalledWith(undefined);
  });

  it("loads the next page on request", () => {
    jobsState = { ...jobsState, hasNextPage: true };
    render(<JobsTable status={undefined} pool="system" onPool={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(fetchNextPage).toHaveBeenCalled();
  });

  it("says so when the queue cannot be read, and when it is empty", () => {
    jobsState = { ...jobsState, error: new Error("down") };
    const { rerender } = render(<JobsTable status="dead" pool={undefined} onPool={vi.fn()} />);
    expect(screen.getByText("The jobs could not be read.")).toBeInTheDocument();

    jobsState = { ...jobsState, error: null, data: undefined };
    rerender(<JobsTable status="dead" pool={undefined} onPool={vi.fn()} />);
    expect(screen.getByText("No jobs here.")).toBeInTheDocument();
  });
});

describe("workers and schedules", () => {
  it("warns when no worker is alive", () => {
    render(<WorkersAndSchedules workers={[]} schedules={[]} />);
    expect(screen.getByText(/nothing in the queue is running/)).toBeInTheDocument();
  });

  it("lists who serves which pools and when each schedule runs next", () => {
    render(
      <WorkersAndSchedules
        workers={[
          {
            id: "host:1:abc",
            hostname: "host",
            pools: ["agent", "system"],
            started_at: new Date().toISOString(),
            heartbeat_at: new Date().toISOString(),
          },
        ]}
        schedules={[
          {
            name: "apply-retention",
            kind: "apply-retention",
            interval_seconds: 86_400,
            next_run_at: "2026-10-20T03:00:00Z",
            last_fired_at: null,
            overlap: "skip",
            misfire: "latest",
          },
        ]}
      />,
    );
    expect(screen.getByText("host:1:abc")).toBeInTheDocument();
    expect(screen.getByText(/Agent runs, System/)).toBeInTheDocument();
    expect(screen.getByText("every day")).toBeInTheDocument();
  });

  it("names an interval in the largest unit it divides into", () => {
    expect(interval(7 * 86_400)).toEqual({ unit: "day", count: 7 });
    expect(interval(3_600)).toEqual({ unit: "hour", count: 1 });
    expect(interval(900)).toEqual({ unit: "minute", count: 15 });
    expect(interval(20)).toEqual({ unit: "minute", count: 1 });
  });
});
