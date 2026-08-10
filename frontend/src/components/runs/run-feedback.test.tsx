import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RunFeedback } from "./run-feedback";
import { apiClient } from "@/lib/api-client";
import type { RunTranscript, RunTranscriptMessage } from "@/types/runs";

/**
 * The run-detail feedback panel: the answers people rated down, and their words.
 *
 * The panel reads the run transcript, keeps the answers rated down, and shows
 * the comment. The tests mock the transcript at the API-client boundary - the
 * transcript route ships on a sibling branch, so this pins the panel's behaviour
 * against the contract rather than against that branch's code.
 *
 * The load-bearing distinction is empty versus failed: on this page an empty
 * state drawn for a failed request would read "nobody complained", which is the
 * one reassuring reading a 502 must never be allowed to borrow.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function message(overrides: Partial<RunTranscriptMessage> = {}): RunTranscriptMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "the refund window is 30 days",
    user_rating: null,
    rating_count: null,
    rating_comment: null,
    ...overrides,
  };
}

function transcript(items: RunTranscriptMessage[]): RunTranscript {
  return { run_id: "run-1", conversation_id: "c1", items, total: items.length };
}

describe("the run's rated-down feedback", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the comment left with a thumb down", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(
      transcript([
        message({
          user_rating: -1,
          rating_count: { likes: 0, dislikes: 1 },
          rating_comment: "it invented a policy we do not have",
        }),
      ]),
    );

    render(<RunFeedback runId="run-1" />, { wrapper });

    expect(await screen.findByText("it invented a policy we do not have")).toBeVisible();
  });

  it("counts anybody's thumb down, not only the reader's own", async () => {
    // A run one person disliked is worth reading even to someone who did not
    // rate it - the same "anybody" the run list marks a 👎 on.
    vi.mocked(apiClient.get).mockResolvedValue(
      transcript([
        message({
          user_rating: null,
          rating_count: { likes: 3, dislikes: 1 },
          rating_comment: "wrong number for Q3",
        }),
      ]),
    );

    render(<RunFeedback runId="run-1" />, { wrapper });

    expect(await screen.findByText("wrong number for Q3")).toBeVisible();
  });

  it("says a thumb down was left without words rather than showing nothing", async () => {
    // And a down-rated turn that produced no text of its own still lists - the
    // rating is the record, the answer only how it ended.
    vi.mocked(apiClient.get).mockResolvedValue(
      transcript([
        message({ user_rating: -1, rating_count: { likes: 0, dislikes: 1 }, content: "" }),
      ]),
    );

    render(<RunFeedback runId="run-1" />, { wrapper });

    expect(await screen.findByText("Rated down, with no comment.")).toBeVisible();
  });

  it("keeps only the answers rated down", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(
      transcript([
        message({ id: "liked", rating_count: { likes: 2, dislikes: 0 }, content: "the good one" }),
        message({
          id: "disliked",
          user_rating: -1,
          rating_count: { likes: 0, dislikes: 1 },
          rating_comment: "the bad one",
        }),
      ]),
    );

    render(<RunFeedback runId="run-1" />, { wrapper });

    expect(await screen.findByText("the bad one")).toBeVisible();
    expect(screen.queryByText("the good one")).toBeNull();
  });

  it("says nothing was rated down when nothing was", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(
      transcript([message({ rating_count: { likes: 1, dislikes: 0 } })]),
    );

    render(<RunFeedback runId="run-1" />, { wrapper });

    expect(await screen.findByText("Nothing rated down")).toBeVisible();
  });

  it("draws a failed request as an error, never as nothing rated down", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));

    render(<RunFeedback runId="run-1" />, { wrapper });

    expect(await screen.findByText("The feedback could not be read")).toBeVisible();
    await waitFor(() => expect(screen.queryByText("Nothing rated down")).toBeNull());
  });
});
