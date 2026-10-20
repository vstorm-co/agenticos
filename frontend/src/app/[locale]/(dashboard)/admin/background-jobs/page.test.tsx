import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BackgroundJobsPage from "./page";

const refetch = vi.fn();
const resumeMutate = vi.fn();
let overview: Record<string, unknown> = {};
let resumeState: Record<string, unknown> = {};

vi.mock("@/hooks/use-background-jobs", () => ({
  useBackgroundJobsOverview: () => overview,
  useBackgroundJobActions: () => ({ resume: resumeState }),
  useBackgroundJobs: () => ({ data: undefined, isPending: false, error: null }),
  // The charts have their own tests (`job-activity.test.tsx`); here they are loading.
  useBackgroundJobsActivity: () => ({ data: undefined, error: null }),
}));

const DATA = {
  counts: { queued: 1, running: 0, dead: 0, succeeded: 0, cancelled: 0 },
  kinds: [
    {
      kind: "ingest-document",
      organization_id: null,
      organization_name: null,
      consecutive_deaths: 5,
      lease_lost: 0,
      paused_at: "2026-10-19T10:00:00Z",
      paused_reason: "five deaths",
    },
  ],
  workers: [],
  schedules: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  resumeState = { mutate: resumeMutate, isPending: false, variables: undefined };
});

describe("the Background jobs page", () => {
  it("waits for the overview", () => {
    overview = { isPending: true };
    render(<BackgroundJobsPage />);
    expect(screen.queryByText("Jobs")).not.toBeInTheDocument();
  });

  it("offers a retry when the queue cannot be read", () => {
    overview = { isPending: false, error: new Error("down"), refetch };
    render(<BackgroundJobsPage />);

    expect(screen.getByText("Couldn't read the queue")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("puts what is paused first and resumes it from there", () => {
    overview = { isPending: false, error: null, data: DATA };
    render(<BackgroundJobsPage />);

    expect(screen.getByText("A kind of job is paused")).toBeInTheDocument();
    expect(screen.getByText("Jobs")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(resumeMutate).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "ingest-document", organization_id: null }),
    );
  });

  it("holds the button of the kind that is resuming", () => {
    overview = { isPending: false, error: null, data: DATA };
    resumeState = {
      mutate: resumeMutate,
      isPending: true,
      variables: { kind: "ingest-document", organization_id: null },
    };
    render(<BackgroundJobsPage />);

    expect(screen.getByRole("button", { name: "Resume" })).toBeDisabled();
  });

  it("filters the table by the state chosen in the counts", () => {
    overview = { isPending: false, error: null, data: DATA };
    render(<BackgroundJobsPage />);

    const queued = screen.getByRole("button", { name: /Queued/ });
    fireEvent.click(queued);
    expect(queued).toHaveAttribute("aria-pressed", "true");
  });
});
