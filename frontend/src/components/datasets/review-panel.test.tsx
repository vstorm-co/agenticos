import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { caseScore } from "@/test-utils/scores";

import type { CaseScore } from "@/types/scoring";
import { ReviewPanel } from "./review-panel";

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

const SCORE: CaseScore = caseScore({ passed: false, outcome: false });

beforeEach(() => {
  vi.clearAllMocks();
  state.answer = {};
  state.calls = [];
});

describe("ReviewPanel", () => {
  it("opens on what waits for a decision, and says how answers get there", () => {
    render(<ReviewPanel datasetId="d1" canDecide />);

    expect(screen.getByText("Nothing is waiting for a decision")).toBeInTheDocument();
    expect(screen.getByText(/An eval run's page sends here/)).toBeInTheDocument();
    expect(state.calls.at(-1)).toEqual(["d1", { pending: true, skip: 0, limit: 50 }]);
  });

  it("shows every result on request, back from the first page", async () => {
    render(<ReviewPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("combobox", { name: "Show" }));
    await userEvent.click(screen.getByRole("option", { name: "All results" }));

    expect(screen.getByText("No results yet")).toBeInTheDocument();
    expect(state.calls.at(-1)).toEqual(["d1", { pending: false, skip: 0, limit: 50 }]);
  });

  it("puts each eval run's scores under one heading, and hand-graded ones under another", () => {
    state.answer = {
      scores: [
        caseScore({ id: "a", eval_run_id: "e1", agent_id: "x", agent_name: "Support" }),
        caseScore({ id: "b", eval_run_id: "e1", agent_id: "x", agent_name: "Support" }),
        caseScore({ id: "c", eval_run_id: null, agent_id: null }),
      ],
      total: 3,
    };
    render(<ReviewPanel datasetId="d1" canDecide={false} />);

    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual([
      expect.stringMatching(/^Eval run · .+ · Support$/),
      "Graded by hand · An agent that is gone",
    ]);
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });

  it("steps back a page when a decision empties the last one", async () => {
    state.answer = { scores: [SCORE], total: 51 };
    const { rerender } = render(<ReviewPanel datasetId="d1" canDecide />);
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(state.calls.at(-1)).toEqual(["d1", { pending: true, skip: 50, limit: 50 }]);

    state.answer = { scores: [], total: 50 };
    rerender(<ReviewPanel datasetId="d1" canDecide />);

    expect(state.calls.at(-1)).toEqual(["d1", { pending: true, skip: 0, limit: 50 }]);
  });

  it("offers a retry when the scores could not be read", async () => {
    state.answer = { error: new Error("502") };
    render(<ReviewPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(state.refetch).toHaveBeenCalled();
  });

  it("shows a skeleton while loading", () => {
    state.answer = { isLoading: true };
    render(<ReviewPanel datasetId="d1" canDecide />);

    expect(screen.queryByText("Nothing is waiting for a decision")).toBeNull();
  });

  it("records a decision and a withdrawal, and says so", async () => {
    state.answer = { scores: [{ ...SCORE, human_passed: true }], total: 1 };
    state.verdict.mockResolvedValue({});
    render(<ReviewPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("button", { name: "Mark failed" }));
    await userEvent.click(screen.getByRole("button", { name: "Withdraw decision" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Decision withdrawn"));
    expect(toast.success).toHaveBeenCalledWith("Decision saved");
    expect(state.verdict).toHaveBeenCalledWith({ scoreId: "s1", passed: false, note: null });
  });

  it("says why a decision or a review request was refused", async () => {
    state.answer = { scores: [SCORE], total: 1 };
    state.verdict.mockRejectedValue(new Error("Not yours"));
    state.review.mockRejectedValue(new Error("Gone"));
    render(<ReviewPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("button", { name: "Mark passed" }));
    await userEvent.click(screen.getByRole("button", { name: "Send to review" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Gone"));
    expect(toast.error).toHaveBeenCalledWith("Not yours");
  });

  it("sends a score to review", async () => {
    state.answer = { scores: [SCORE], total: 1 };
    state.review.mockResolvedValue({});
    render(<ReviewPanel datasetId="d1" canDecide />);

    await userEvent.click(screen.getByRole("button", { name: "Send to review" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Sent to the review queue"));
    expect(state.review).toHaveBeenCalledWith("s1");
  });

  it("offers no decision to somebody who may not decide", () => {
    state.answer = { scores: [SCORE], total: 1 };
    render(<ReviewPanel datasetId="d1" canDecide={false} />);

    expect(screen.queryByRole("button", { name: "Mark passed" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Send to review" })).toBeNull();
  });
});
