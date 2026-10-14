import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseScore } from "@/types/scoring";
import { ScoresPanel } from "./scores-panel";

const state = vi.hoisted(() => ({
  answer: {} as Record<string, unknown>,
  calls: [] as unknown[],
  verdict: vi.fn(),
  review: vi.fn(),
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-scoring", () => ({
  useScores: (...args: unknown[]) => {
    state.calls.push(args);
    return {
      scores: [],
      total: 0,
      isLoading: false,
      error: null,
      refetch: state.refetch,
      verdict: { mutateAsync: state.verdict, isPending: false },
      review: { mutateAsync: state.review, isPending: false },
      ...state.answer,
    };
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

const SCORE: CaseScore = {
  id: "s1",
  dataset_id: "d1",
  case_id: "c1",
  case_revision_id: "r1",
  run_id: null,
  judge: null,
  results: [],
  passed: false,
  review_state: "none",
  human_passed: null,
  human_note: null,
  reviewed_by_user_id: null,
  reviewed_at: null,
  created_by_user_id: null,
  created_at: "2026-10-13T00:00:00Z",
  outcome: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  state.answer = {};
  state.calls = [];
});

describe("ScoresPanel", () => {
  it("says where scores come from when there are none", () => {
    render(<ScoresPanel datasetId="d1" canDecide />);

    expect(screen.getByText("No scores yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Activity" })).toHaveAttribute("href", "/runs");
  });

  it("narrows to the review queue, back to the first page", async () => {
    render(<ScoresPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("switch", { name: "Only awaiting review" }));

    expect(screen.getByText("Nothing is waiting for review")).toBeInTheDocument();
    expect(state.calls.at(-1)).toEqual(["d1", { pending: true, skip: 0, limit: 50 }]);
  });

  it("offers a retry when the scores could not be read", async () => {
    state.answer = { error: new Error("502") };
    render(<ScoresPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(state.refetch).toHaveBeenCalled();
  });

  it("shows a skeleton while loading", () => {
    state.answer = { isLoading: true };
    render(<ScoresPanel datasetId="d1" canDecide />);

    expect(screen.queryByText("No scores yet")).toBeNull();
  });

  it("records a verdict and a withdrawal, and says so", async () => {
    state.answer = { scores: [{ ...SCORE, human_passed: true }], total: 1 };
    state.verdict.mockResolvedValue({});
    render(<ScoresPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("button", { name: "Mark failed" }));
    await userEvent.click(screen.getByRole("button", { name: "Withdraw verdict" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Verdict withdrawn"));
    expect(toast.success).toHaveBeenCalledWith("Verdict saved");
    expect(state.verdict).toHaveBeenCalledWith({ scoreId: "s1", passed: false, note: null });
  });

  it("says why a verdict or a review request was refused", async () => {
    state.answer = { scores: [SCORE], total: 1 };
    state.verdict.mockRejectedValue(new Error("Not yours"));
    state.review.mockRejectedValue(new Error("Gone"));
    render(<ScoresPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("button", { name: "Mark passed" }));
    await userEvent.click(screen.getByRole("button", { name: "Send to review" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Gone"));
    expect(toast.error).toHaveBeenCalledWith("Not yours");
  });

  it("sends a score to review", async () => {
    state.answer = { scores: [SCORE], total: 1 };
    state.review.mockResolvedValue({});
    render(<ScoresPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("button", { name: "Send to review" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Sent to the review queue"));
    expect(state.review).toHaveBeenCalledWith("s1");
  });

  it("offers no verdict to somebody who may not decide", () => {
    state.answer = { scores: [SCORE], total: 1 };
    render(<ScoresPanel datasetId="d1" canDecide={false} />);

    expect(screen.queryByRole("button", { name: "Mark passed" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Send to review" })).toBeNull();
  });
});
