import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SCORING } from "@/lib/scoring";
import { caseScore } from "@/test-utils/scores";
import type { Dataset } from "@/types/datasets";
import type { CaseScore } from "@/types/scoring";
import { ReviewPanel } from "./review-panel";

type Query = { pending: boolean; limit?: number; [filter: string]: unknown };

const state = vi.hoisted(() => ({
  answer: {} as Record<string, unknown>,
  otherTotal: 0,
  calls: [] as [string, Record<string, unknown>][],
  verdict: vi.fn(),
  review: vi.fn(),
  withdraw: vi.fn(),
  rescore: vi.fn(),
  toCriterion: vi.fn(),
  refetch: vi.fn(),
  canRun: true,
  canViewRuns: true,
  agents: [] as { id: string; name: string }[],
}));
vi.mock("@/hooks/use-scoring", () => ({
  useNoteToCriterion: () => ({ mutateAsync: state.toCriterion, isPending: false }),
  useScores: (datasetId: string, query: Query) => {
    state.calls.push([datasetId, query]);
    const counting = query.limit === 1;
    return {
      scores: [],
      total: counting ? state.otherTotal : 0,
      isLoading: false,
      error: null,
      refetch: state.refetch,
      verdict: { mutateAsync: state.verdict, isPending: false },
      review: { mutateAsync: state.review, isPending: false },
      withdraw: { mutateAsync: state.withdraw, isPending: false },
      rescore: { mutateAsync: state.rescore, isPending: false },
      ...(counting ? {} : state.answer),
    };
  },
}));
vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents: state.agents }) }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (perm: string) =>
      (perm !== "datasets:run" || state.canRun) && (perm !== "runs:view" || state.canViewRuns),
  }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
import { toast } from "sonner";

const SCORE: CaseScore = caseScore({ passed: false, outcome: false });

function dataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    id: "d1",
    name: "Refunds",
    description: null,
    visibility: "org",
    owner_user_id: null,
    latest_version: 1,
    case_count: 2,
    can_edit: true,
    can_run: true,
    pending_proposals: 0,
    scoring: DEFAULT_SCORING,
    judge_name: "Eval judge",
    stats: {
      with_reference: 0,
      with_counter_example: 0,
      with_tool_calls: 0,
      with_checks: 0,
      expectation_mix: [],
      by_source: { manual: 2, import: 0, conversation: 0, synthetic: 0 },
      top_tags: [{ tag: "billing", cases: 2 }],
    },
    created_at: "2026-10-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

/** The main listing's query, not the one counting the other segment. */
const listed = () => state.calls.filter(([, query]) => query.limit !== 1).at(-1)?.[1];

beforeEach(() => {
  vi.clearAllMocks();
  state.answer = {};
  state.otherTotal = 0;
  state.calls = [];
  state.agents = [{ id: "a1", name: "Support" }];
  state.canRun = true;
  state.canViewRuns = true;
});

describe("ReviewPanel", () => {
  it("opens on what waits for a decision, and says how answers get there", () => {
    state.answer = { total: 0 };
    state.otherTotal = 7;
    render(<ReviewPanel dataset={dataset()} />);

    expect(screen.getByText("Nothing is waiting for a decision")).toBeInTheDocument();
    expect(screen.getByText(/An eval run sends here the regressions/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Waiting for a decision (0)" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "All results (7)" })).toBeInTheDocument();
    expect(listed()).toMatchObject({ pending: true, skip: 0, limit: 50 });
  });

  it("shows every result on request, counting what waits beside it", async () => {
    state.otherTotal = 2;
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("button", { name: /All results/ }));

    expect(screen.getByText("No results yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Waiting for a decision (2)" })).toBeInTheDocument();
    expect(listed()).toMatchObject({ pending: false, skip: 0 });
  });

  it("narrows by outcome, agent and tag, and back", async () => {
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    await userEvent.click(screen.getByRole("option", { name: "Not graded" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Support" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "billing" }));
    expect(listed()).toMatchObject({ outcome: "not_graded", agentId: "a1", tag: "billing" });

    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    await userEvent.click(screen.getByRole("option", { name: "Any outcome" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Every agent" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "Every tag" }));
    expect(listed()).toMatchObject({ outcome: null, agentId: null, tag: null });
  });

  it("offers no agent or tag filter where there is nothing to pick", () => {
    state.agents = [];
    render(<ReviewPanel dataset={dataset({ stats: { ...dataset().stats, top_tags: [] } })} />);

    expect(screen.queryByRole("combobox", { name: "Agent" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Tag" })).toBeNull();
  });

  it("puts each eval run's scores under a heading linking the run, in the order they were graded", () => {
    state.answer = {
      scores: [
        caseScore({
          id: "b",
          eval_run_id: "e1",
          agent_id: "x",
          agent_name: "Support",
          question: "Second",
          created_at: "2026-10-13T09:01:00Z",
        }),
        caseScore({
          id: "a",
          eval_run_id: "e1",
          agent_id: "x",
          agent_name: "Support",
          question: "First",
          created_at: "2026-10-13T09:00:00Z",
        }),
        caseScore({ id: "c", eval_run_id: null, agent_id: null }),
      ],
      total: 3,
    };
    render(<ReviewPanel dataset={dataset({ can_edit: false })} />);

    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual([
      expect.stringMatching(/^Eval run · .+ · Support$/),
      "Graded by hand · An agent that is gone",
    ]);
    expect(screen.getAllByRole("link", { name: "Eval run ↗" })[0]).toHaveAttribute(
      "href",
      "/agents/x/evals/e1",
    );
    const questions = screen.getAllByRole("link", { name: /^(First|Second)$/ });
    expect(questions.map((link) => link.textContent)).toEqual(["First", "Second"]);
    expect(screen.queryByRole("button", { name: /from the queue/ })).toBeNull();
  });

  it("links no eval run or Activity run to a reader without runs:view", () => {
    state.canViewRuns = false;
    state.answer = {
      scores: [
        caseScore({ id: "a", eval_run_id: "e1", agent_id: "x", agent_name: "Support" }),
        caseScore({ id: "b", eval_run_id: null, run_id: "run-1" }),
      ],
      total: 2,
    };
    render(<ReviewPanel dataset={dataset()} />);

    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "Eval run ↗" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Scored run" })).toBeNull();
  });

  it("takes a group out of the queue undecided, and says so", async () => {
    state.answer = {
      scores: [caseScore({ id: "a" }), caseScore({ id: "b" })],
      total: 2,
    };
    state.withdraw.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("Gone"));
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("button", { name: "Remove 2 from the queue" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("2 results taken out of the queue"),
    );
    expect(state.withdraw).toHaveBeenCalledWith(["a", "b"]);

    await userEvent.click(screen.getByRole("button", { name: "Remove 2 from the queue" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Gone"));
  });

  it("steps back a page when a decision empties the last one", async () => {
    state.answer = { scores: [SCORE], total: 51 };
    const { rerender } = render(<ReviewPanel dataset={dataset()} />);
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(listed()).toMatchObject({ pending: true, skip: 50 });

    state.answer = { scores: [], total: 50 };
    rerender(<ReviewPanel dataset={dataset()} />);

    expect(listed()).toMatchObject({ pending: true, skip: 0 });
  });

  it("offers a retry when the scores could not be read", async () => {
    state.answer = { error: new Error("502") };
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(state.refetch).toHaveBeenCalled();
  });

  it("shows a skeleton while loading", () => {
    state.answer = { isLoading: true };
    render(<ReviewPanel dataset={dataset()} />);

    expect(screen.queryByText("Nothing is waiting for a decision")).toBeNull();
  });

  it("records a decision and a withdrawal, each with an undo that puts back what was", async () => {
    state.answer = { scores: [{ ...SCORE, human_passed: true, human_note: "ok" }], total: 1 };
    state.verdict.mockResolvedValue({});
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("button", { name: "Mark failed" }));
    await userEvent.click(screen.getByRole("button", { name: "Withdraw decision" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Decision withdrawn", expect.anything()),
    );
    expect(toast.success).toHaveBeenCalledWith("Decision saved", expect.anything());
    expect(state.verdict).toHaveBeenCalledWith({ scoreId: "s1", passed: false, note: "ok" });

    const [, options] = vi.mocked(toast.success).mock.calls[0]! as unknown as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect(options.action.label).toBe("Undo");
    options.action.onClick();
    expect(state.verdict).toHaveBeenLastCalledWith({ scoreId: "s1", passed: true, note: "ok" });
  });

  it("says why a decision or a review request was refused", async () => {
    state.answer = { scores: [SCORE], total: 1 };
    state.verdict.mockRejectedValue(new Error("Not yours"));
    state.review.mockRejectedValue(new Error("Gone"));
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("button", { name: "Mark passed" }));
    await userEvent.click(screen.getByRole("button", { name: "Send to review" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Gone"));
    expect(toast.error).toHaveBeenCalledWith("Not yours");
  });

  it("sends a score to review", async () => {
    state.answer = { scores: [SCORE], total: 1 };
    state.review.mockResolvedValue({ ...SCORE, review_state: "pending" });
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("button", { name: "Send to review" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Sent to the review queue"));
    expect(state.review).toHaveBeenCalledWith("s1");
  });

  it("says when a newer answer to the case already waits instead", async () => {
    state.answer = { scores: [SCORE], total: 1 };
    state.review.mockResolvedValue({ ...SCORE, review_state: "none" });
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("button", { name: "Send to review" }));

    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(
        "A newer answer to this case already waits for review, so this one was not sent.",
      ),
    );
    expect(toast.success).not.toHaveBeenCalledWith("Sent to the review queue");
  });

  it("offers no decision to somebody who may not decide", () => {
    state.answer = { scores: [SCORE], total: 1 };
    render(<ReviewPanel dataset={dataset({ can_edit: false })} />);

    expect(screen.queryByRole("button", { name: "Mark passed" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Send to review" })).toBeNull();
  });

  it("scores an ungraded answer again, and a group's ungraded answers at once", async () => {
    const ungraded = (id: string) =>
      caseScore({
        id,
        eval_run_id: "e1",
        agent_id: "x",
        agent_name: "Support",
        unscored_reason: "judge_output_invalid",
      });
    state.answer = {
      scores: [
        ungraded("a"),
        ungraded("b"),
        caseScore({ id: "c", eval_run_id: "e1", agent_id: "x" }),
      ],
      total: 3,
    };
    state.rescore
      .mockResolvedValueOnce({ rescored: [ungraded("a"), ungraded("b")], kept: [] })
      .mockResolvedValueOnce({ rescored: [], kept: ["a"] })
      .mockRejectedValueOnce(new Error("Gone"));
    render(<ReviewPanel dataset={dataset()} />);

    expect(
      screen.getAllByText(/The judge answered in a form that could not be read\./),
    ).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Score 2 ungraded answers again" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Scored 2 answers again"));
    expect(state.rescore).toHaveBeenCalledWith(["a", "b"]);

    await userEvent.click(screen.getAllByRole("button", { name: "Score again" })[0]!);
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Every scorer had already reached a verdict, so nothing was scored again.",
      ),
    );
    expect(state.rescore).toHaveBeenLastCalledWith(["a"]);

    await userEvent.click(screen.getAllByRole("button", { name: "Score again" })[1]!);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Gone"));
  });

  it.each([
    ["run this dataset, whatever the role says", { canRun: true, canViewRuns: true }, false],
    [
      "read the runs it would read the answers back from",
      { canRun: true, canViewRuns: false },
      true,
    ],
  ])("offers no scoring again to somebody who may not %s", (_who, perms, canRunIt) => {
    Object.assign(state, perms);
    state.answer = {
      scores: [
        caseScore({ id: "a", unscored_reason: "judge_budget" }),
        caseScore({ id: "b", unscored_reason: "judge_budget" }),
      ],
      total: 2,
    };
    render(<ReviewPanel dataset={dataset({ can_run: canRunIt })} />);

    expect(screen.getAllByText(/budget is spent/)).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /again/ })).toBeNull();
    expect(screen.queryByText(/Fix the cause/)).toBeNull();
  });

  it("offers scoring again to who may run this dataset by a grant alone", () => {
    Object.assign(state, { canRun: false, canViewRuns: true });
    state.answer = {
      scores: [caseScore({ id: "a", unscored_reason: "judge_budget" })],
      total: 1,
    };
    render(<ReviewPanel dataset={dataset({ can_run: true })} />);

    expect(screen.getByRole("button", { name: "Score again" })).toBeInTheDocument();
  });

  it("makes a decided score's note a criterion of its case or of every case", async () => {
    const decided = caseScore({ human_passed: false, human_note: "Must cite the policy" });
    state.answer = { scores: [decided], total: 1 };
    state.toCriterion
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("AI assistance is off"));
    render(<ReviewPanel dataset={dataset()} />);

    await userEvent.click(screen.getByRole("button", { name: "for this case" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "The note is now a judge criterion of this case, in a new version of the dataset.",
      ),
    );
    expect(state.toCriterion).toHaveBeenCalledWith({ score: decided, target: "case" });
    await userEvent.click(screen.getByRole("button", { name: "for every case" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "The note is now one of the judge's criteria for every case, and the judge is on.",
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "for every case" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("AI assistance is off"));
  });

  it("offers no note to turn into a criterion before a decision, or to a reader", () => {
    state.answer = {
      scores: [
        caseScore({ id: "a", human_passed: null, human_note: null }),
        caseScore({ id: "b", human_passed: true, human_note: "Fine" }),
      ],
      total: 2,
    };
    render(<ReviewPanel dataset={dataset({ can_edit: false })} />);

    expect(screen.queryByRole("button", { name: "for this case" })).toBeNull();
  });
});
