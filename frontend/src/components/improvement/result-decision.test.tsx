import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { Improvement, ImprovementIteration, MeasurementNoise } from "@/types/improvement";
import { ReadOnlyProvider } from "./read-only";
import { ResultStep } from "./result-decision";

const state = vi.hoisted(() => ({
  topics: [] as { id: string }[],
  discard: vi.fn(),
  select: vi.fn(),
  judges: [{ id: "judge-1", system_key: "eval_judge" }] as { id: string; system_key: string }[],
}));
vi.mock("./outcome", () => ({
  DOCUMENTS_ANCHOR: "improvement-documents",
  useSessionTopics: () => ({ topics: state.topics, added: [] }),
  ResultSummary: () => <p>Counters</p>,
  KnowledgeDocuments: () => <p>Topic list</p>,
}));
vi.mock("./round-results", () => ({
  AttemptRow: ({ round }: { round: ImprovementIteration }) => <p>Row {round.number}</p>,
  AttemptSummary: ({ round }: { round: ImprovementIteration }) => (
    <span>Summary {round.number}</span>
  ),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgentsOfKind: () => ({
    agents: state.judges,
    isLoading: false,
    error: null,
  }),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({
    estimateContinuation: { mutateAsync: vi.fn() },
    continueSession: { mutateAsync: vi.fn(), isPending: false },
    discard: { mutateAsync: state.discard, isPending: false },
    selectRound: { mutateAsync: state.select, isPending: false },
  }),
}));

const BASE = SESSION.iterations[0]!;
const round = (number: number, verdict: ImprovementIteration["verdict"], broken = 0) => ({
  ...BASE,
  id: `r${number}`,
  number,
  verdict,
  verdict_detail: { fixed: 0, broken },
});
/** Three attempts, none better, the second breaking two questions, at the attempt limit. */
const EXHAUSTED: Improvement = {
  ...SESSION,
  status: "stopped",
  stop_reason: "max_iterations",
  iteration: 3,
  best_iteration_id: "r1",
  iterations: [round(1, "no_change"), round(2, "regression", 2), round(3, "no_change")],
};

function show(
  session: Improvement,
  { candidate = false, canAccept = true, onAccept = vi.fn() } = {},
) {
  return render(
    <ResultStep
      session={session}
      agent="Refund desk"
      candidate={candidate}
      canAccept={canAccept}
      knowledgeCheck={null}
      onAccept={onAccept}
      onStarted={vi.fn()}
    />,
  );
}

const primary = (name: string | RegExp) =>
  expect(screen.getByRole("button", { name })).toHaveClass("bg-action");

beforeEach(() => {
  vi.clearAllMocks();
  state.topics = [];
  state.judges = [{ id: "judge-1", system_key: "eval_judge" }];
});

it("leads with the better attempt and sends the person to accept it", async () => {
  const onAccept = vi.fn();
  show(SESSION, { candidate: true, onAccept });
  expect(
    screen.getByText("Attempt 1 made Refund desk better: 3 questions fixed and none broke."),
  ).toBeInTheDocument();
  primary("Review and accept the changes");
  await userEvent.click(screen.getByRole("button", { name: "Review and accept the changes" }));
  expect(onAccept).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Try again" })).not.toHaveClass("bg-action");
});

it("names a chosen attempt that was not better, and holds Accept while the selection changed", () => {
  show(
    { ...SESSION, best_iteration_id: "r2", iterations: [BASE, round(2, "regression", 1)] },
    { candidate: true, canAccept: false },
  );
  expect(screen.getByText("You chose attempt 2 to accept.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Review and accept the changes" })).toBeDisabled();
});

it("says no attempt helped and which broke, and leads to the missing topics", () => {
  state.topics = [{ id: "t1" }, { id: "t2" }, { id: "t3" }, { id: "t4" }];
  show(EXHAUSTED);
  expect(
    screen.getByText(
      "None of the 3 attempts made Refund desk better. Attempt 2 made it worse: 2 questions broke. " +
        "4 topics are missing from the knowledge base. That used all 3 attempts this session allows.",
    ),
  ).toBeInTheDocument();
  const topics = screen.getByRole("link", { name: "Draft the ones you need" });
  expect(topics).toHaveAttribute("href", "#improvement-documents");
  expect(topics).toHaveClass("bg-action");
  expect(screen.getByRole("button", { name: "End without changes" })).toHaveClass("border");
  expect(screen.queryByRole("button", { name: /Try again|Improve again/ })).toBeNull();
  expect(screen.getByText("Topic list").parentElement).toHaveAttribute(
    "id",
    "improvement-documents",
  );
  expect(screen.getAllByText(/^Row \d$/)).toHaveLength(3);
});

it("offers to end, or to start over with better test questions, when nothing is left", async () => {
  show(EXHAUSTED);
  primary("End without changes");
  expect(screen.getByRole("link", { name: "Start a new session" })).toHaveAttribute(
    "href",
    "/agents/a1/improve/new",
  );
  expect(
    screen.getByText(/once you add test questions where Refund desk answers badly/),
  ).toBeInTheDocument();
  expect(screen.queryByText("Topic list")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "End without changes" }));
  expect(await screen.findByText("Discard this session’s suggestions?")).toBeInTheDocument();
});

it("makes trying again the primary action while attempts are left", () => {
  state.topics = [{ id: "t1" }];
  show({
    ...EXHAUSTED,
    stop_reason: "regression",
    iteration: 1,
    iterations: [round(1, "regression", 1)],
  });
  expect(screen.getByText(/^The attempt did not make Refund desk better\./)).toBeInTheDocument();
  primary("Try again");
  expect(screen.getByRole("link", { name: "Draft the ones you need" })).not.toHaveClass(
    "bg-action",
  );
});

it("retries a failed step first, and says the session failed", () => {
  show({ ...SESSION, status: "failed", stage: "proposing", stop_reason: "proposal" });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "The session stopped on an error before it finished. The proposal step failed.",
  );
  primary("Retry this step within the spending limit");
});

it("says no attempt was measured, and offers nothing to someone who only reads", () => {
  render(
    <ReadOnlyProvider value="viewOnly">
      <ResultStep
        session={{ ...SESSION, status: "stopped", stop_reason: "no_proposal", iterations: [] }}
        agent="Refund desk"
        candidate={false}
        canAccept
        knowledgeCheck={<p>Knowledge check</p>}
        onAccept={vi.fn()}
        onStarted={vi.fn()}
      />
    </ReadOnlyProvider>,
  );
  expect(
    screen.getByText(
      "No attempt was measured, so nothing shows whether Refund desk got better. No applicable changes were found.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText("What you can do")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.queryByText("Attempts")).toBeNull();
});

it("names the published attempt and its version once the session is decided", () => {
  show({
    ...EXHAUSTED,
    status: "published",
    stop_reason: null,
    best_iteration_id: "r2",
    published_version: 7,
  });
  expect(
    screen.getByText(
      "None of the 3 attempts made Refund desk better. Attempt 2 made it worse: 2 questions broke. " +
        "Attempt 2 was published as version 7.",
    ),
  ).toBeInTheDocument();
});

it("says a better attempt was kept as a draft, and a publish whose version is unknown", () => {
  const view = show({ ...SESSION, status: "accepted" });
  expect(
    screen.getByText(
      "Attempt 1 made Refund desk better: 3 questions fixed and none broke. " +
        "Attempt 1 was accepted as a draft.",
    ),
  ).toBeInTheDocument();
  view.unmount();
  show({ ...SESSION, status: "published", published_version: null });
  expect(screen.getByText(/Attempt 1 was published\.$/)).toBeInTheDocument();
});

const NOISE: MeasurementNoise = {
  noisy: true,
  held_out: 10,
  baseline_low: 0.5,
  baseline_high: 0.7,
  baseline_spread: 2,
  unstable: 6,
  within: 6,
  shared: 10,
  between: 2,
  too_few_shared: false,
  by_attempt: [{ number: 1, baseline_unstable: 3, candidate_unstable: 3 }],
  examples: [
    {
      case_id: "c1",
      input: "Do you deliver within Poland?",
      attempts: [
        { number: 1, baseline: [false, true, false], candidate: [true, null] },
        { number: 2, baseline: [true], candidate: [true] },
      ],
    },
  ],
};

it("says plainly when the test cannot tell the versions apart, and how to fix it", async () => {
  show({ ...EXHAUSTED, measurement_noise: NOISE });
  expect(
    screen.getByText(
      /^The test can't tell a better version from a worse one: today's version of Refund desk scored 50% and 70% on the questions its attempts shared\. None of the 3 attempts/,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", {
      name: "Make the grading criteria yes-or-no instead of a 1–5 scale",
    }),
  ).toHaveAttribute("href", "/datasets/d1?tab=grading");
  expect(
    screen.getByRole("link", { name: "Check length and format with a rule instead of the judge" }),
  ).toHaveAttribute("href", "/datasets/d1?tab=cases");
  expect(
    screen.getByRole("link", { name: "Add questions, up to about 30 kept aside" }),
  ).toHaveAttribute("href", "/datasets/d1?tab=cases");
  expect(screen.getByRole("link", { name: "Grade with a stronger judge model" })).toHaveAttribute(
    "href",
    "/agents/judge-1",
  );
  primary("End without changes");
  const list = screen.getByText(
    "6 of the 10 questions kept aside were graded differently with nothing changed",
  );
  expect(list.closest("details")).not.toHaveAttribute("open");
  await userEvent.click(list);
  expect(screen.getByText("Do you deliver within Poland?")).toBeVisible();
  expect(screen.getAllByRole("img", { name: "Failed" })).toHaveLength(2);
  expect(screen.getAllByRole("img", { name: "Not graded" })).toHaveLength(1);
});

it("names the questions graded both ways when today's score itself held still", () => {
  show({
    ...EXHAUSTED,
    measurement_noise: { ...NOISE, baseline_low: 0.6, baseline_high: 0.6, baseline_spread: 0 },
  });
  expect(
    screen.getByText(
      /^The test can't tell a better version from a worse one: 6 of the 10 questions kept aside got a different grade when asked again, with nothing changed\./,
    ),
  ).toBeInTheDocument();
});

it("judges noise only within attempts when they shared too few questions, and says so", () => {
  show({
    ...EXHAUSTED,
    measurement_noise: {
      ...NOISE,
      within: 3,
      shared: 2,
      between: null,
      too_few_shared: true,
      baseline_low: null,
      baseline_high: null,
      baseline_spread: null,
      by_attempt: [
        { number: 1, baseline_unstable: 2, candidate_unstable: 1 },
        { number: 2, baseline_unstable: 0, candidate_unstable: 1 },
      ],
    },
  });
  expect(
    screen.getByText(
      /^The test can't tell a better version from a worse one: 3 of the 10 questions kept aside across the 2 attempts got/,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "The attempts kept aside only 2 of the same questions, too few to judge noise between them.",
    ),
  ).toBeInTheDocument();
});

it("only notes the noise beside a better attempt, without the diagnosis", () => {
  show({ ...SESSION, measurement_noise: NOISE }, { candidate: true });
  expect(
    screen.getByText(/^Attempt 1 made Refund desk better: 3 questions fixed and none broke\.$/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/^The test is noisy: today's version of Refund desk scored 50% and 70%/),
  ).toBeInTheDocument();
  expect(screen.queryByText("Make the test reliable before you try again")).toBeNull();
  expect(screen.queryByText(/graded differently with nothing changed/)).toBeNull();
});

it("leaves a quiet test without any noise wording", () => {
  show({ ...EXHAUSTED, measurement_noise: { ...NOISE, noisy: false } });
  expect(screen.queryByText(/can't tell a better version/)).toBeNull();
});

it("sends a stronger judge to the dataset's grading when the organization has no default judge", () => {
  state.judges = [];
  show({ ...EXHAUSTED, measurement_noise: NOISE });
  expect(screen.getByRole("link", { name: "Grade with a stronger judge model" })).toHaveAttribute(
    "href",
    "/datasets/d1?tab=grading",
  );
});

it("hints that another attempt probably won't help, without stopping the session", () => {
  const twice = {
    ...EXHAUSTED,
    stop_reason: "no_change",
    iteration: 2,
    iterations: [round(1, "no_change"), round(2, "no_change")],
    round_hint: "no_change" as const,
  };
  const view = show(twice);
  const headline = screen.getByText(/^None of the 2 attempts made Refund desk better\./);
  expect(headline).toHaveTextContent(
    "Two attempts in a row changed nothing, so another one probably won't help.",
  );
  expect(headline).not.toHaveTextContent(
    /No reproducible improvement|attempts this session allows/,
  );
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  view.unmount();
  show({ ...twice, stop_reason: "inconclusive", round_hint: "inconclusive" });
  expect(
    screen.getByText(
      /could not be graded reliably, which points at the test rather than the agent\./,
    ),
  ).toBeInTheDocument();
});

it("names the attempt limit only once it is really reached", () => {
  show({ ...EXHAUSTED, stop_reason: "no_change", round_hint: "no_change" });
  const headline = screen.getByText(/^None of the 3 attempts made Refund desk better\./);
  expect(headline).toHaveTextContent("That used all 3 attempts this session allows.");
  expect(headline).not.toHaveTextContent(/probably won't help/);
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
});

it("puts the choice of attempt in the decision card, not inside an attempt's details", async () => {
  show(EXHAUSTED);
  const choice = screen.getByRole("group", { name: "Which attempt to keep" });
  expect(choice).toHaveTextContent("Summary 1Summary 2Summary 3");
  await userEvent.click(screen.getByRole("radio", { name: "Keep attempt 3" }));
  await userEvent.click(screen.getByRole("button", { name: "Keep attempt 3 anyway" }));
  expect(state.select).toHaveBeenCalledWith(3);
});

it("leaves the choice out when one attempt was measured", () => {
  show({ ...EXHAUSTED, iterations: [EXHAUSTED.iterations[0]!] });
  expect(screen.queryByRole("group", { name: "Which attempt to keep" })).not.toBeInTheDocument();
});

it("gives the whole session's cost above the attempts, so a row's cost is not read as it", () => {
  show({ ...EXHAUSTED, spent_usd: "0.0912" });
  expect(screen.getByText("The whole session, analysis included: $0.0912")).toBeInTheDocument();
});
