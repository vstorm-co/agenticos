import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { Improvement, ImprovementIteration } from "@/types/improvement";
import { ReadOnlyProvider } from "./read-only";
import { ResultStep } from "./result-decision";

const state = vi.hoisted(() => ({ topics: [] as { id: string }[], discard: vi.fn() }));
vi.mock("./outcome", () => ({
  DOCUMENTS_ANCHOR: "improvement-documents",
  useSessionTopics: () => ({ topics: state.topics }),
  ResultSummary: () => <p>Counters</p>,
  KnowledgeDocuments: () => <p>Topic list</p>,
}));
vi.mock("./round-results", () => ({
  AttemptRow: ({ round }: { round: ImprovementIteration }) => <p>Row {round.number}</p>,
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({
    estimateContinuation: { mutateAsync: vi.fn() },
    continueSession: { mutateAsync: vi.fn(), isPending: false },
    discard: { mutateAsync: state.discard, isPending: false },
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
  expect(screen.getByRole("button", { name })).toHaveClass("bg-primary");

beforeEach(() => {
  vi.clearAllMocks();
  state.topics = [];
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
  expect(screen.getByRole("button", { name: "Try again" })).not.toHaveClass("bg-primary");
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
  expect(topics).toHaveClass("bg-primary");
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
    iterations: [round(1, "regression", 1)],
  });
  expect(screen.getByText(/^The attempt did not make Refund desk better\./)).toBeInTheDocument();
  primary("Try again");
  expect(screen.getByRole("link", { name: "Draft the ones you need" })).not.toHaveClass(
    "bg-primary",
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

it("says a running session's result is only so far, and offers no decision yet", () => {
  show({ ...EXHAUSTED, status: "running", stage: "proposing", stop_reason: null });
  expect(
    screen.getByText("The session is still working, so this is the result so far."),
  ).toBeInTheDocument();
  expect(screen.queryByText("What you can do")).toBeNull();
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
