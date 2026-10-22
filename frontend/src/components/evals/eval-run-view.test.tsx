import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/auth-store";
import type { User } from "@/types/auth";
import type { EvalRun } from "@/types/eval-runs";
import { FLIP, SUMMARY, arm, attempt, comparison, evalCase, evalRun } from "@/test-utils/eval-runs";
import { ApiError } from "@/lib/api-error";
import { EvalRunView } from "./eval-run-view";

const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
  },
}));

const navigation = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => navigation.params,
  usePathname: () => "/agents/agent-1/evals/run-1",
  useRouter: () => ({ push: vi.fn(), replace: navigation.replace }),
}));

const review = vi.hoisted(() => ({
  canEdit: false,
  canRun: false,
  mutate: vi.fn(),
  rescore: vi.fn(),
}));
const loaded = vi.hoisted(() => ({
  agent: { can_run: true, can_edit: true } as
    { can_run: boolean; can_edit: boolean; can_publish?: boolean } | undefined,
}));
vi.mock("@/hooks/use-agents", () => ({ useAgent: () => ({ agent: loaded.agent }) }));

vi.mock("@/hooks/use-datasets", () => ({
  useDataset: () => ({ dataset: { can_edit: review.canEdit, can_run: review.canRun } }),
}));

const state = vi.hoisted(() => ({
  run: {} as Record<string, unknown>,
  cases: {} as Record<string, unknown>,
  comparison: undefined as unknown,
  casesArgs: [] as unknown[],
  comparisonArgs: [] as unknown[],
  refetchComparison: (() => undefined) as () => unknown,
  refetchCases: (() => undefined) as () => unknown,
  comparisonError: null as Error | null,
}));
vi.mock("@/hooks/use-eval-runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-eval-runs")>();
  return {
    ...actual,
    useEvalRun: () => state.run,
    useEvalCases: (...args: unknown[]) => {
      state.casesArgs.push(args);
      return { refetch: state.refetchCases, ...state.cases };
    },
    useSendToReview: () => ({ mutate: review.mutate, isPending: false }),
    useRescoreRun: () => ({ mutate: review.rescore, isPending: false }),
    useEvalComparison: (...args: unknown[]) => {
      state.comparisonArgs.push(args);
      return {
        comparison: state.comparison,
        error: state.comparisonError,
        refetch: state.refetchComparison,
      };
    },
  };
});

const cancel = { mutate: vi.fn() };
const testAgain = vi.hoisted(() => ({ props: [] as unknown[] }));
vi.mock("./start-eval-dialog", () => ({
  StartEvalDialog: (props: { onOpenChange: (open: boolean) => void }) => {
    testAgain.props.push(props);
    return <button onClick={() => props.onOpenChange(false)}>start-dialog</button>;
  },
}));

/** A draft measured against v6 in the same run, which it made worse. */
function worseDraft() {
  state.run = {
    ...state.run,
    run: evalRun({
      arms: [
        arm({ source: "draft", version_number: null, agent_version_id: null }),
        arm({ id: "arm-0", role: "baseline", version_number: 6 }),
      ],
      attempts_total: 6,
    }),
  };
  state.comparison = comparison({
    candidate: { ...comparison().candidate, source: "draft", version_number: null },
    baseline: { ...comparison().candidate, run_id: "run-1", arm_id: "arm-0", version_number: 6 },
    paired: true,
    verdict: "worse",
    regressions_confirmed: 4,
    fixed_unconfirmed: 0,
    candidate_summary: { ...SUMMARY, pass_rate: 0.22 },
    baseline_summary: { ...SUMMARY, pass_rate: 0.67 },
    cases: [FLIP, { ...FLIP, case_id: "case-2", flip: "unchanged" }],
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  review.canEdit = false;
  review.canRun = false;
  review.mutate = vi.fn();
  review.rescore = vi.fn();
  loaded.agent = { can_run: true, can_edit: true };
  navigation.params = new URLSearchParams();
  useAuthStore.setState({ user: null });
  state.comparisonError = null;
  state.casesArgs = [];
  state.comparisonArgs = [];
  state.run = { run: evalRun(), isLoading: false, error: null, refetch: vi.fn(), cancel };
  state.cases = { cases: [evalCase()], total: 1, isLoading: false, error: null };
  state.comparison = comparison();
});

describe("EvalRunView", () => {
  it("says which suite started a run, and on what", () => {
    state.run = {
      ...state.run,
      run: evalRun({ suite: { id: "suite-1", name: "Nightly", trigger: "schedule" } }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByText("Started by the suite Nightly on its schedule.")).toBeInTheDocument();
  });

  it("says what the suite a check ran on would have said of it", () => {
    state.run = {
      ...state.run,
      run: evalRun({
        suite_check: {
          suite_id: "suite-1",
          name: "Nightly",
          suite_exists: true,
          status: "failed",
          reasons: [{ code: "pass_rate_below", value: 0.5, limit: 0.9, detail: null }],
        },
      }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nightly" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=evals",
    );
  });

  it("leads with the verdict, then each side, how they compare and every case", async () => {
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByText("refunds v3 · v7")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: /v7 breaks 1 case that passed on Draft, every time it was asked: “How long do I have to return it\?” \(3 of 3\)\./,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Breaks cases")).toBeInTheDocument();
    // Each case as it settled, the first answers alone on hover.
    expect(screen.getByTitle("First answers alone: 75% → 75%")).toHaveTextContent(
      "Pass rate 75% → 75%",
    );
    expect(screen.getByText("4 cases · 4 answers + no confirming reruns")).toBeInTheDocument();
    expect(
      screen.getByText(
        /spent \$0.04 of an estimated \$0.05, plus up to \$0.02 for confirming reruns/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the agent's evals" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=evals",
    );
    expect(screen.getByRole("link", { name: "Back to Build" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=build",
    );
    // A published version is not what Publish acts on, and the draft was not measured.
    expect(screen.queryByRole("link", { name: "Publish" })).toBeNull();
    expect(screen.queryByRole("link", { name: "See what changed" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    expect(screen.getByText("How the two compare")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Undecided" })).toBeInTheDocument();

    const caseRow = screen.getByRole("button", { name: /How long do I have to return it/ });
    expect(within(caseRow).getByRole("img", { name: "v7 · gpt-4.1: passed" })).toBeVisible();
    expect(within(caseRow).getByText("Confirmed regression")).toBeInTheDocument();
    await userEvent.click(caseRow);
    expect(screen.getByText("You have 30 days.")).toBeInTheDocument();
    await userEvent.click(caseRow);
    expect(screen.queryByText("You have 30 days.")).not.toBeInTheDocument();
  });

  it("says a draft made things worse, what changed, and shows the cases that broke", async () => {
    worseDraft();
    loaded.agent = { can_run: true, can_edit: true, can_publish: true };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(
      screen.getByRole("heading", {
        name: /Draft breaks 4 cases that passed on v6, every time it was asked: “How long do I have to return it\?” \(3 of 3\) and 3 more\..*Pass rate 67% → 22%/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 answers \+ 2 confirming reruns/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See what changed" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=history&from=6&run=run-1&arm=arm-1",
    );
    expect(screen.getByRole("link", { name: "Publish" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=build&publish=1",
    );

    await userEvent.click(screen.getByRole("button", { name: "Show the 4 cases that broke" }));
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ caseIds: ["case-1"], skip: 0 }),
    ]);
    expect(screen.getByText("Showing the case that broke.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show every case" }));
    expect(state.casesArgs.at(-1)).toEqual(["run-1", expect.objectContaining({ caseIds: null })]);
  });

  it("shows the first hundred of many broken cases, as many as one request names", async () => {
    worseDraft();
    state.comparison = {
      ...(state.comparison as object),
      cases: Array.from({ length: 101 }, (_, i) => ({ ...FLIP, case_id: `case-${i}` })),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    await userEvent.click(screen.getByRole("button", { name: /Show the 4 cases that broke/ }));
    const [, query] = state.casesArgs.at(-1) as [string, { caseIds: string[] }];
    expect(query.caseIds).toHaveLength(100);
    expect(screen.getByText("Showing the first 100 of the 101 cases that broke.")).toBeVisible();
  });

  it("puts Publish first only when nothing broke for sure", () => {
    worseDraft();
    state.comparison = {
      ...(state.comparison as object),
      verdict: "better",
      regressions_confirmed: 0,
      fixed_confirmed: 1,
      cases: [
        { ...FLIP, flip: "fixed", baseline: false, candidate: true, candidate_reruns: [true] },
      ],
    };
    loaded.agent = { can_run: true, can_edit: true, can_publish: true };
    const { unmount } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(
      screen.getByRole("heading", {
        name: /Draft fixes 1 case that failed on v6, every time it was asked: “How long do I have to return it\?” \(2 of 2\)/,
      }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Publish" }).className).toContain("bg-primary");
    unmount();

    // A case the draft never finished answering is no reason to publish either.
    const [draft, base] = (state.run.run as EvalRun).arms;
    state.run = {
      ...state.run,
      run: evalRun({ arms: [{ ...draft!, summary: { ...SUMMARY, incomplete: 1 } }, base!] }),
    };
    const unfinished = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("link", { name: "Publish" }).className).not.toContain("bg-primary");
    unfinished.unmount();

    // A confirmed regression is a reason not to publish, beside any number of fixes.
    state.comparison = {
      ...(state.comparison as object),
      verdict: "mixed",
      regressions_confirmed: 3,
      cases: [FLIP],
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Mixed")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /Mixed: Draft breaks 3 cases and fixes 1 against v6/ }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Publish" }).className).not.toContain("bg-primary");
  });

  it("says which cases a check left out, and leads back to the suggestions it checked", () => {
    state.run = {
      ...(state.run as object),
      run: evalRun({
        excluded_case_ids: ["case-7", "case-8"],
        arms: [arm({ source: "explicit" })],
      }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(
      screen.getByText(
        "2 cases were left out: taken from the conversations the checked change was derived from.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the suggestions" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=build",
    );
  });

  it("leads a skill change's check back to Skills, where the change waits", () => {
    state.run = {
      ...(state.run as object),
      run: evalRun({ arms: [arm({ source: "version", skill_ids: ["skill-1"] })] }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("link", { name: "Back to the skill change" })).toHaveAttribute(
      "href",
      "/skills",
    );
    expect(screen.queryByRole("link", { name: "Back to the suggestions" })).toBeNull();
  });

  it("says when the verdict could not be read, and reads it again", async () => {
    const refetch = vi.fn();
    state.refetchComparison = refetch;
    state.comparison = undefined;
    state.comparisonError = new Error("boom");
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByRole("alert")).toHaveTextContent("The verdict could not be read.");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("says when the confirmed changes make it worse as a whole", () => {
    worseDraft();
    state.comparison = { ...(state.comparison as object), overall: "worse" };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Breaks cases").className).toContain("destructive");
    expect(screen.getByText("Worse overall")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: /Worse overall: across every confirmed change, Draft does worse than v6\./,
      }),
    ).toBeVisible();
  });

  it("keeps a run that breaks a case mixed, however much better it is overall", () => {
    worseDraft();
    state.comparison = {
      ...(state.comparison as object),
      verdict: "mixed",
      regressions_confirmed: 1,
      fixed_confirmed: 10,
      overall: "better",
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Mixed").className).toContain("warning");
    // A qualifier beside the verdict, never a green one in its place.
    expect(screen.getByText("Better overall").className).not.toContain("success");
  });

  it("says what it sent to review itself, and when its judge graded its own model", () => {
    state.run = {
      ...state.run,
      run: evalRun({ routed_to_review: 3, routed_replacing: 1, judge_model_profile_id: "m1" }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(
      screen.getByText(
        "This run sent 3 answers to review itself: the regressions it confirmed and the answers the judge failed to grade. That replaced 1 older answer still waiting on the same case.",
      ),
    ).toBeVisible();
    expect(screen.getByText(/The judge graded on gpt-4.1, the model that answered/)).toBeVisible();
  });

  it("says when it could not send its answers to review, beside the way to send them", () => {
    review.canEdit = true;
    state.run = {
      ...state.run,
      run: evalRun({
        routing_error: { code: "REVIEW_CLOSED", message: "The review queue is closed." },
      }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(
      screen.getByText(
        "This run couldn't send its answers to review itself, so send the failed ones by hand. Why: The review queue is closed.",
      ),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Send the failed case to review" })).toBeVisible();
  });

  it("draws no flip while the run answers, and names the side a case was not graded on", () => {
    state.run = { ...state.run, run: evalRun({ status: "running", first_done: 1 }) };
    const { unmount } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByText("Confirmed regression")).toBeNull();
    unmount();

    const undecided = (id: string, side: "baseline" | "candidate") => ({
      ...FLIP,
      case_id: id,
      flip: "incomplete" as const,
      confirmed: false,
      [side]: null,
    });
    state.run = { ...state.run, run: evalRun() };
    state.cases = {
      cases: [evalCase(), evalCase({ case_id: "case-2" })],
      total: 2,
      isLoading: false,
      error: null,
    };
    state.comparison = comparison({
      cases: [undecided("case-1", "candidate"), undecided("case-2", "baseline")],
    });
    const again = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Not graded on v7")).toBeInTheDocument();
    expect(screen.getByText("Not graded on Draft")).toBeInTheDocument();
    again.unmount();

    // With nothing to compare with, the only side there is.
    state.comparison = comparison({ baseline: null, cases: [undecided("case-2", "baseline")] });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Not graded on v7")).toBeInTheDocument();
  });

  it("says no change held when nothing reproduced", () => {
    state.comparison = comparison({
      verdict: "no_difference",
      regressions_confirmed: 0,
      regressions_unconfirmed: 1,
      fixed_unconfirmed: 1,
      cases: [],
    });
    const { unmount } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("No reproducible change")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: /No change held: 2 cases changed once and came out differently when asked again, so any difference in pass rate between v7 and Draft on refunds is not a reproducible change\./,
      }),
    ).toBeVisible();
    expect(screen.queryByText(/test on a steadier model/)).toBeNull();
    unmount();

    state.comparison = comparison({
      verdict: "no_difference",
      regressions_confirmed: 0,
      regressions_unconfirmed: 0,
      fixed_unconfirmed: 0,
      cases: [],
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(
      screen.getByRole("heading", {
        name: /No change held: v7 does as well as Draft on refunds\./,
      }),
    ).toBeVisible();
  });

  it("suggests a steadier model when much changed and nothing held", () => {
    const unsteady = /Run it again, or test on a steadier model/;
    state.comparison = comparison({
      verdict: "no_difference",
      regressions_unconfirmed: 4,
      fixed_unconfirmed: 2,
      cases: [],
    });
    const many = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText(unsteady)).toBeVisible();
    many.unmount();

    // One change, but the pass rate moved by more than a fifth.
    state.comparison = comparison({
      verdict: "no_difference",
      regressions_unconfirmed: 1,
      candidate_summary: { ...SUMMARY, pass_rate: 0.33 },
      baseline_summary: { ...SUMMARY, pass_rate: 0.7 },
      cases: [],
    });
    const far = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText(unsteady)).toBeVisible();
    far.unmount();

    // One change and no rates to set apart.
    state.comparison = comparison({
      verdict: "no_difference",
      regressions_unconfirmed: 1,
      candidate_summary: { ...SUMMARY, pass_rate: null },
      baseline_summary: null,
      cases: [],
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByText(unsteady)).toBeNull();
  });

  it("grades again the answers the judge left ungraded, for who may run the dataset", async () => {
    state.run = { ...state.run, run: evalRun({ ungraded_score_ids: ["s1", "s2"] }) };
    const { unmount } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText(/2 answers were not graded/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Grade again" })).toBeNull();
    unmount();

    review.canRun = true;
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Grade again" }));
    expect(review.rescore).toHaveBeenCalledWith(["s1", "s2"], expect.any(Object));
    const { onSuccess, onError } = review.rescore.mock.calls[0]![1] as {
      onSuccess: (count: number) => void;
      onError: (failure: Error) => void;
    };
    onSuccess(2);
    expect(toastSuccess).toHaveBeenCalledWith("2 answers graded again");
    onError(new Error("judge down"));
    expect(toastError).toHaveBeenCalled();
  });

  it("opens the case a link names, and every case after", async () => {
    navigation.params = new URLSearchParams("case=case-1");
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ caseIds: ["case-1"] }),
    ]);
    expect(screen.getByText("Showing the one case you opened.")).toBeInTheDocument();
    expect(screen.getByText("You have 30 days.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show every case" }));
    expect(state.casesArgs.at(-1)).toEqual(["run-1", expect.objectContaining({ caseIds: null })]);
  });

  it("shows no verdict for a run with no candidate to give one about", () => {
    state.run = { ...state.run, run: evalRun({ arms: [] }) };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByRole("link", { name: "Back to Build" })).toBeNull();
  });

  it("names no rerun allowance when a run had none", () => {
    state.run = { ...state.run, run: evalRun({ rerun_ceiling_usd: "0" }) };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText(/of an estimated \$0.05$/)).toBeInTheDocument();
  });

  it("sends what failed to review, for who may edit the dataset", async () => {
    review.canEdit = true;
    review.mutate = vi.fn((_arm: unknown, options: { onSuccess: (sent: unknown) => void }) =>
      options.onSuccess({ queued: 1, replaced: 0, already: 0 }),
    );
    const { unmount } = render(<EvalRunView agentId="agent-1" runId="run-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Send the failed case to review" }));

    expect(review.mutate).toHaveBeenCalledWith("arm-1", expect.anything());
    expect(toastSuccess).toHaveBeenCalledWith("1 case sent to review.");
    unmount();

    review.mutate = vi.fn((_arm: unknown, options: { onSuccess: (sent: unknown) => void }) =>
      options.onSuccess({ queued: 3, replaced: 2, already: 1 }),
    );
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Send the failed case to review" }));
    expect(toastSuccess).toHaveBeenLastCalledWith(
      "3 cases sent to review, replacing 2 older ones that were waiting; 1 not sent: already waiting, decided or older than the one waiting.",
    );
  });

  it("says when sending to review was refused", async () => {
    review.canEdit = true;
    review.mutate = vi.fn((_arm: unknown, options: { onError: (e: Error) => void }) =>
      options.onError(new Error("refused")),
    );
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    await userEvent.click(screen.getByRole("button", { name: /to review/ }));
    expect(toastError).toHaveBeenCalled();
  });

  it("offers no review to who may not edit the dataset, or when nothing failed", () => {
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("button", { name: /to review/ })).toBeNull();
    cleanup();

    review.canEdit = true;
    state.run = {
      ...state.run,
      run: evalRun({ arms: [arm({ unsent_failed: 0 })] }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("button", { name: /to review|failed case/ })).toBeNull();
  });

  it("offers to send what the run did not send itself", () => {
    review.canEdit = true;
    state.run = {
      ...state.run,
      run: evalRun({ routed_to_review: 1, arms: [arm({ unsent_failed: 2 })] }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("button", { name: "Send the other 2 failed cases" })).toBeVisible();
  });

  it("names each side's ungraded cases and keeps Publish from leading over them", () => {
    worseDraft();
    state.comparison = {
      ...(state.comparison as object),
      verdict: "better",
      regressions_confirmed: 0,
      fixed_confirmed: 1,
      cases: [
        { ...FLIP, flip: "fixed", baseline: false, candidate: true, candidate_reruns: [true] },
      ],
    };
    state.run = {
      ...state.run,
      run: evalRun({
        ungraded_score_ids: ["s1", "s2"],
        arms: [
          arm({
            source: "draft",
            version_number: null,
            ungraded_cases: [
              { case_id: "c1", input: "$700 TV, can I return it?" },
              { case_id: "c2", input: "Is shipping free?" },
            ],
          }),
          arm({ id: "arm-0", role: "baseline", version_number: 6 }),
        ],
      }),
    };
    loaded.agent = { can_run: true, can_edit: true, can_publish: true };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(
      screen.getByText(
        "2 cases of Draft were not graded: “$700 TV, can I return it?” and 1 more. Grade again before deciding.",
      ),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Publish" }).className).not.toContain("bg-primary");
  });

  it("says a run is confirming its flips once every first answer is in", () => {
    state.comparison = undefined;
    state.run = {
      ...state.run,
      run: evalRun({
        status: "running",
        first_done: 4,
        first_total: 4,
        attempts_done: 5,
        attempts_total: 8,
      }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(
      screen.getByText(
        "Every first answer is in. Confirming the cases that changed: 1 of 4 reruns in.",
      ),
    ).toBeVisible();
  });

  it("shows the cases that broke at least once when some did not break again", () => {
    worseDraft();
    state.comparison = { ...(state.comparison as object), regressions_unconfirmed: 1 };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(
      screen.getByRole("button", { name: "Show the 5 cases that broke at least once" }),
    ).toBeVisible();
  });

  it("says a reader without access cannot open the run, rather than that it broke", () => {
    state.run = {
      ...state.run,
      run: undefined,
      error: new ApiError(403, "Insufficient permissions"),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("You can't open this eval run")).toBeVisible();
  });

  it("marks a case a person's review overturned", () => {
    state.cases = {
      cases: [
        evalCase({
          attempts: [
            attempt({
              outcome: true,
              score: { id: "s1", passed: false, human_passed: true } as never,
            }),
          ],
        }),
      ],
      total: 1,
      isLoading: false,
      error: null,
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Corrected by a person")).toBeInTheDocument();
  });

  it("offers to test again, not to publish, once the draft moved on", async () => {
    worseDraft();
    state.run = { ...state.run, run: { ...(state.run.run as object), draft_changed: true } };
    loaded.agent = { can_run: true, can_edit: true, can_publish: true };
    const { unmount } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    // Testing again starts a run of the draft, which this reader may not.
    expect(screen.getByText("The draft changed after this run.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Test again" })).toBeNull();
    unmount();

    review.canRun = true;
    loaded.agent = undefined;
    const again = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("button", { name: "Test again" })).toBeNull();
    again.unmount();

    loaded.agent = { can_run: true, can_edit: true };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("link", { name: "Publish" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Test again" }));
    expect(testAgain.props.at(-1)).toEqual(
      expect.objectContaining({ agentId: "agent-1", datasetId: "ds-1", target: "compare" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "start-dialog" }));
    expect(screen.queryByRole("button", { name: "start-dialog" })).toBeNull();
  });

  it("offers no publish to who may not publish", () => {
    worseDraft();
    const { unmount } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("link", { name: "Publish" })).toBeNull();
    unmount();

    // An editor of this agent who may not publish it - a Member on their own.
    loaded.agent = { can_run: true, can_edit: true, can_publish: false };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("link", { name: "Publish" })).toBeNull();
  });

  it("calls a run with nothing before it the first result", () => {
    state.comparison = comparison({
      baseline: null,
      verdict: null,
      regressions_confirmed: 0,
      fixed_unconfirmed: 0,
      baseline_summary: null,
      cases: [],
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(
      screen.getByRole("heading", {
        name: "This is the first result of v7 on refunds: 75% of cases pass. Later versions are compared with it.",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("How the two compare")).toBeNull();
    expect(screen.queryByRole("button", { name: /that broke/ })).toBeNull();
  });

  it("says why two sides cannot be compared", () => {
    state.comparison = comparison({
      verdict: "invalid",
      invalid_reason: "The two sides were graded by a different judge, model or rubric.",
      baseline_summary: null,
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("heading", { name: /v7 and Draft cannot be compared/ })).toBeVisible();
    expect(screen.getByText(/graded by a different judge, model or rubric/)).toBeVisible();
  });

  it("while it answers, says how far it got and holds the comparison back", async () => {
    state.run = {
      ...state.run,
      run: evalRun({
        status: "running",
        first_done: 1,
        attempts_done: 1,
        error: "A case ran into a budget.",
      }),
    };
    state.cases = {
      cases: [evalCase({ attempts: [attempt({ status: "running", outcome: null })] })],
      total: 1,
      isLoading: false,
      error: null,
    };
    cancel.mutate.mockImplementation((_: unknown, options: { onError: (e: Error) => void }) =>
      options.onError(new Error("Only whoever started this eval can stop it")),
    );
    // Whoever started it may stop it.
    useAuthStore.setState({ user: { id: "u1" } as User });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByText(/1 of 4 first answers in/)).toBeInTheDocument();
    expect(screen.getByText("The comparison appears when both sides finish.")).toBeVisible();
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByText("How the two compare")).toBeNull();
    expect(screen.getByRole("columnheader", { name: "Pending" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "v7 · gpt-4.1: pending" })).toBeInTheDocument();
    expect(screen.getByText("A case ran into a budget.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(cancel.mutate).toHaveBeenCalled();
    expect(toastError).toHaveBeenCalled();
    // A live run's table and its verdict are read again while it answers.
    expect(state.casesArgs.at(-1)).toEqual(["run-1", expect.objectContaining({ live: true })]);
    expect(state.comparisonArgs.at(-1)).toEqual(["run-1", { arm: "arm-1", live: true }]);
    cleanup();

    // Somebody else may not, unless they may edit this agent - whatever the role.
    useAuthStore.setState({ user: { id: "u2" } as User });
    loaded.agent = { can_run: true, can_edit: false };
    const other = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
    other.unmount();
    loaded.agent = { can_run: true, can_edit: true };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("button", { name: "Stop" })).toBeVisible();
  });

  it("reads the verdict and the cases once more when the run ends, after its last reruns", () => {
    const refetch = vi.fn();
    const refetchCases = vi.fn();
    state.refetchComparison = refetch;
    state.refetchCases = refetchCases;
    state.run = { ...state.run, run: evalRun({ status: "running" }) };
    const { rerender } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(refetch).not.toHaveBeenCalled();

    state.run = { ...state.run, run: evalRun({ status: "completed" }) };
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(refetchCases).toHaveBeenCalledTimes(1);
  });

  it("compares the model a reader picks when several ran", async () => {
    state.run = {
      ...state.run,
      run: evalRun({ arms: [arm(), arm({ id: "arm-2", model_label: "claude" })] }),
    };
    state.cases = { cases: [evalCase()], total: 60, isLoading: false, error: null };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(state.comparisonArgs.at(-1)).toEqual(["run-1", { arm: "arm-1", live: false }]);
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(state.casesArgs.at(-1)).toEqual(["run-1", expect.objectContaining({ skip: 25 })]);

    await userEvent.click(screen.getByRole("combobox", { name: "Compare this model" }));
    await userEvent.click(screen.getByRole("option", { name: "v7 · claude" }));
    expect(state.comparisonArgs.at(-1)).toEqual(["run-1", { arm: "arm-2", live: false }]);
    // The outcome filter reads the picked model's answers too, from their first page.
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ arm: "arm-2", skip: 0 }),
    ]);
  });

  it("moves a run opened under another agent to the agent that ran it", () => {
    navigation.params = new URLSearchParams("case=case-1");
    state.run = { ...state.run, run: evalRun({ agent_id: "agent-2" }) };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(navigation.replace).toHaveBeenCalledWith("/agents/agent-2/evals/run-1?case=case-1");
    expect(screen.queryByRole("link", { name: /back/i })).toBeNull();
  });

  it("moves a run with nothing asked of it to its agent's address alone", () => {
    state.run = { ...state.run, run: evalRun({ agent_id: "agent-2" }) };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(navigation.replace).toHaveBeenCalledWith("/agents/agent-2/evals/run-1");
  });

  it("tells an answer that never finished from one that was not decided", () => {
    state.cases = {
      cases: [
        evalCase({ attempts: [attempt({ status: "failed", outcome: null })] }),
        evalCase({ case_id: "case-2", attempts: [attempt({ outcome: null })] }),
      ],
      total: 2,
      isLoading: false,
      error: null,
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("img", { name: "v7 · gpt-4.1: did not finish" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "v7 · gpt-4.1: undecided" })).toBeInTheDocument();
  });

  it("filters the cases by outcome and tag, back to the first page", async () => {
    state.cases = {
      cases: [
        evalCase({ attempts: [attempt({ outcome: false })] }),
        evalCase({
          case_id: "case-2",
          input: "Lost receipt?",
          tags: [],
          attempts: [attempt({ outcome: null })],
        }),
      ],
      total: 60,
      isLoading: false,
      error: null,
    };
    state.comparison = comparison({
      cases: [
        { ...FLIP, flip: "fixed", confirmed: false },
        { ...FLIP, case_id: "case-2", flip: "unchanged" },
      ],
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Fixed, unconfirmed")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "v7 · gpt-4.1: failed" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "v7 · gpt-4.1: undecided" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(state.casesArgs.at(-1)).toEqual(["run-1", expect.objectContaining({ skip: 25 })]);

    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    await userEvent.click(screen.getByRole("option", { name: "Failed" }));
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ outcome: "failed", tag: null, skip: 0 }),
    ]);
    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "#refunds" }));
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ outcome: "failed", tag: "refunds" }),
    ]);
    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    await userEvent.click(screen.getByRole("option", { name: "All outcomes" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "All tags" }));
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ outcome: null, tag: null }),
    ]);
  });

  it("reads the arms, the flips and the cases under the tag a reader picks", async () => {
    state.run = {
      ...state.run,
      run: evalRun({
        arms: [
          arm({ by_tag: { refunds: { ...SUMMARY, pass_rate: 0.5 } } }),
          arm({ id: "arm-0", role: "baseline", version_number: 6, by_tag: {} }),
        ],
      }),
    };
    state.comparison = comparison({
      regressions_confirmed: 1,
      fixed_confirmed: 1,
      fixed_unconfirmed: 0,
      cases: [FLIP, { ...FLIP, case_id: "case-2", flip: "fixed", tags: ["shipping"] }],
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    const count = (label: string) => screen.getByText(label).nextSibling?.textContent;
    expect(count("Confirmed fixes")).toBe("1");

    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "#refunds" }));

    expect(screen.getByText("Side by side on #refunds")).toBeInTheDocument();
    const candidate = screen.getByRole("row", { name: /v7 · gpt-4\.1/ });
    const baseline = screen.getByRole("row", { name: /v6 · gpt-4\.1/ });
    expect(within(candidate).getByText("50%")).toBeInTheDocument();
    expect(within(baseline).getAllByText("—").length).toBeGreaterThan(0);
    expect(count("Confirmed regressions")).toBe("1");
    expect(count("Confirmed fixes")).toBe("0");
    expect(screen.getByText(/1 case tagged #refunds compared/)).toBeInTheDocument();
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ tag: "refunds", skip: 0 }),
    ]);

    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "All tags" }));
    expect(screen.getByText("Side by side")).toBeInTheDocument();
    expect(count("Confirmed fixes")).toBe("1");
  });

  it("holds placeholders while the cases load, and says when they could not be read", () => {
    state.comparison = undefined;
    state.run = {
      ...state.run,
      run: evalRun({ arms: [arm({ by_tag: {} })], attempts_done: 0, attempts_total: 0 }),
    };
    state.cases = { cases: [], total: 0, isLoading: true, error: null };
    const { rerender } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("combobox", { name: "Tag" })).not.toBeInTheDocument();
    expect(screen.queryByText("How the two compare")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading")).toBeNull();

    state.cases = { cases: [], total: 0, isLoading: false, error: new Error("boom") };
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("refunds v3 · v7")).toBeInTheDocument();
  });

  it("holds a placeholder while the run loads, and offers a retry when it cannot be read", async () => {
    state.run = { ...state.run, run: undefined, isLoading: true };
    const { rerender } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    const refetch = vi.fn();
    state.run = { run: undefined, isLoading: false, error: new Error("gone"), refetch, cancel };
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });
});
