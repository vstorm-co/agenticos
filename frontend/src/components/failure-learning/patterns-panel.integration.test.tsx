import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PatternsPanel } from "./patterns-panel";
import type { FailurePattern } from "@/lib/failure-learning-api";

const pattern = (overrides: Partial<FailurePattern> = {}): FailurePattern => ({
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
  ...overrides,
});

describe("PatternsPanel", () => {
  it("shows each pattern with its count, and labels what mining cannot see", () => {
    render(
      <PatternsPanel
        patterns={[pattern()]}
        isLoading={false}
        error={null}
        canTrack={false}
        onTrack={vi.fn()}
      />,
    );

    expect(screen.getByText("Helper")).toBeInTheDocument();
    expect(screen.getByText(/4 occurrences/)).toBeInTheDocument();
    // The caveats are labelled, not hidden: per-model counts are approximate
    // and a hang with a fresh heartbeat is invisible to mining.
    expect(screen.getByText(/Per-model patterns are approximate/)).toBeInTheDocument();
    expect(screen.getByText(/keeps beating its heartbeat/)).toBeInTheDocument();
  });

  it("marks a pattern with an open entry, and offers no second track", () => {
    render(
      <PatternsPanel
        patterns={[pattern({ already_tracked: true })]}
        isLoading={false}
        error={null}
        canTrack={true}
        onTrack={vi.fn()}
      />,
    );

    expect(screen.getByText("Already tracked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Track" })).not.toBeInTheDocument();
  });

  it("hides the track control from a caller who may not curate", () => {
    render(
      <PatternsPanel
        patterns={[pattern()]}
        isLoading={false}
        error={null}
        canTrack={false}
        onTrack={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Track" })).not.toBeInTheDocument();
  });

  it("tracks a pattern through the form, with the curator's title and summary", async () => {
    const user = userEvent.setup();
    const onTrack = vi.fn();
    render(
      <PatternsPanel
        patterns={[pattern()]}
        isLoading={false}
        error={null}
        canTrack={true}
        onTrack={onTrack}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Track" }));
    await user.type(screen.getByLabelText("Summary"), "The agent keeps sending bad requests.");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(onTrack).toHaveBeenCalledWith(
        expect.objectContaining({ pattern_key: "failed:ModelHTTPError:400" }),
        expect.objectContaining({
          title: expect.stringContaining("ModelHTTPError:400"),
          summary: "The agent keeps sending bad requests.",
        }),
      ),
    );
  });

  it("says when there is nothing recurring, and why a failure may be missing", () => {
    render(
      <PatternsPanel
        patterns={[]}
        isLoading={false}
        error={null}
        canTrack={true}
        onTrack={vi.fn()}
      />,
    );

    expect(screen.getByText("No recurring failures in the last 7 days.")).toBeInTheDocument();
  });
});
