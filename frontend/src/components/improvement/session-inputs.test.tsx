import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { ImprovementEvidence } from "@/types/improvement";
import { StartQuestionSet, StartSignals, TestQuestions } from "./session-inputs";
import { ReadOnlyProvider } from "./read-only";
import { Understand } from "./understand";
const state = vi.hoisted(() => ({
  sources: null as ImprovementEvidence | null,
  sourceError: null as Error | null,
  loading: false,
  attentionError: null as Error | null,
  rated: 5,
  total: 21,
  questions: [
    {
      id: "q1",
      input: "Return window?",
      improvement_partition: "train",
      reference_answer: "30 days",
    },
    { id: "q2", input: "Shipping?", improvement_partition: "holdout", reference_answer: null },
  ],
  questionError: null as Error | null,
  datasetHook: vi.fn(),
  share: "0.5" as string | undefined,
  evidenceHook: vi.fn(),
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovementEvidence: (...args: unknown[]) => {
    state.evidenceHook(...args);
    return {
      evidence: state.sources,
      isLoading: state.loading,
      error: state.sourceError,
      refetch: state.refetch,
    };
  },
}));
vi.mock("@/hooks/use-usage-stats", () => ({
  useAgentAttention: () => ({
    agents: state.rated ? [{ agent_id: "a1", rated_down: state.rated, failed_runs: 2 }] : [],
    isLoading: state.loading,
    error: state.attentionError,
  }),
}));
vi.mock("./write-questions", () => ({
  WriteQuestions: ({ more, onReady }: { more: number; onReady: (id: string) => void }) => (
    <button onClick={() => onReady("d9")}>Write {more} more</button>
  ),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDataset: () => ({ dataset: { id: "d1", improvement_holdout_share: state.share } }),
  useDatasetCases: (...args: unknown[]) => {
    state.datasetHook(...args);
    return {
      cases: state.questions,
      total: state.total,
      isLoading: state.loading,
      error: state.questionError,
      refetch: state.refetch,
    };
  },
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.sources = {
    sample_limit: 20,
    training_failures: 3,
    items: [
      {
        run_id: "r1",
        conversation_id: "c1",
        kind: "chat",
        status: "completed",
        rating: -1,
        question: "Refund?",
        answer: "90 days",
        comments: ["Wrong policy"],
        branch: "unknown",
        reason: null,
      },
      {
        run_id: "r2",
        conversation_id: null,
        kind: "train_eval",
        status: "train_eval_failure",
        rating: 0,
        question: "Deadline?",
        answer: null,
        comments: [],
        branch: "agent",
        reason: null,
      },
      {
        run_id: "r3",
        conversation_id: null,
        kind: "chat",
        status: "completed",
        rating: -1,
        question: "Shipping fee?",
        answer: "Unknown",
        comments: [],
        branch: "missing_knowledge",
        reason: "No source passage",
      },
      {
        run_id: "r4",
        conversation_id: "c2",
        kind: "chat",
        status: "completed",
        rating: 1,
        question: null,
        answer: null,
        comments: [],
        branch: "not_a_problem",
        reason: null,
      },
    ],
  };
  state.sourceError = state.attentionError = state.questionError = null;
  state.loading = false;
  state.share = "0.5";
  state.rated = 5;
  state.total = 21;
  state.questions = [
    {
      id: "q1",
      input: "Return window?",
      improvement_partition: "train",
      reference_answer: "30 days",
    },
    { id: "q2", input: "Shipping?", improvement_partition: "holdout", reference_answer: null },
  ];
});
it("shows real signal counts, and no failing test answers before anything was tested", () => {
  render(<StartSignals agentId="a1" datasetId="d1" />);
  for (const count of ["5", "2"]) expect(screen.getByText(count)).toBeInTheDocument();
  expect(screen.queryByText("Test answers marked as failing")).not.toBeInTheDocument();
  expect(state.evidenceHook).toHaveBeenCalledWith("a1", { datasetId: "d1" });
});
it("distinguishes loading, read failures and no learning data", () => {
  state.loading = true;
  const view = render(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.loading = false;
  state.sourceError = new Error("Cannot load sources");
  view.rerender(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.sourceError = null;
  state.attentionError = new Error("Cannot read counts");
  view.rerender(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.attentionError = null;
  state.rated = 0;
  state.sources = { items: [], sample_limit: 20, training_failures: 0 };
  view.rerender(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getAllByText("0")).toHaveLength(2);
  expect(screen.getByText(/Nothing to learn from yet/)).toBeInTheDocument();
});
it("keeps unknown causes explicit and shows quotes, comments, reasons and source links", async () => {
  render(<Understand session={SESSION} />);
  expect(screen.getByText(/no recorded cause/)).toBeInTheDocument();
  expect(screen.getByText("Wrong policy")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "Open conversation" })[0]).toHaveAttribute(
    "href",
    "/chat/c1",
  );
  await userEvent.click(screen.getAllByText("Why we think so")[0]!);
  expect(screen.getByText(/has not been classified/)).toBeInTheDocument();
  expect(screen.getByText("No source passage")).toBeInTheDocument();
  expect(screen.getByText(/test answer failed/)).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /^We found \d+ problems?:/ })).toBeInTheDocument();
  expect(
    screen.getByText("A person rated this answer down and said: “Wrong policy”"),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByText(/^Not a problem to fix \(/));
  expect(screen.getByText(/not by a person/)).toBeInTheDocument();
  expect(screen.getByText("A person rated this answer up.")).toBeInTheDocument();
});
it("does not invent examples when sources are gone or unreadable", () => {
  state.sources = { items: [], sample_limit: 20, training_failures: 0 };
  const view = render(<Understand session={SESSION} />);
  expect(screen.getByText(/Nothing to learn from yet/)).toBeInTheDocument();
  expect(screen.getAllByText(/No selected examples/)).toHaveLength(2);
  state.loading = true;
  view.rerender(<Understand session={{ ...SESSION, status: "running" }} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.loading = false;
  state.sourceError = new Error("Forbidden");
  view.rerender(<Understand session={SESSION} />);
  expect(screen.getByRole("button", { name: "Try reading again" })).toBeInTheDocument();
  state.sourceError = null;
  state.sources = null;
  view.rerender(<Understand session={{ ...SESSION, status: "queued" }} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
});
it("pages the pinned questions and explains train versus holdout", async () => {
  render(<TestQuestions session={SESSION} />);
  expect(state.datasetHook).toHaveBeenCalledWith(SESSION.dataset_id, {
    version: SESSION.dataset_version,
    skip: 0,
    limit: 20,
  });
  expect(screen.getByText("21 test questions")).toBeInTheDocument();
  await userEvent.click(screen.getByText("Review the questions"));
  expect(screen.getByText("A good answer: 30 days")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Previous questions" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Next questions" }));
  expect(state.datasetHook).toHaveBeenCalledWith(SESSION.dataset_id, {
    version: SESSION.dataset_version,
    skip: 20,
    limit: 20,
  });
  expect(screen.getByRole("button", { name: "Next questions" })).toBeDisabled();
  state.datasetHook.mockClear();
  await userEvent.click(screen.getByRole("button", { name: "Previous questions" }));
  expect(state.datasetHook).toHaveBeenCalledWith(SESSION.dataset_id, {
    version: SESSION.dataset_version,
    skip: 0,
    limit: 20,
  });
});
it("offers to write as many questions as the session lacks to measure a change", async () => {
  const short = {
    ...SESSION,
    iterations: [{ ...SESSION.iterations[0]!, verdict_detail: { missing_holdout: 3 } }],
  };
  const view = render(<TestQuestions session={short} />);
  expect(
    screen.getByText(
      "Too few questions to measure a change: 3 more questions not used to write the changes are needed.",
    ),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Write 6 more" }));
  expect(
    screen.getByRole("link", { name: "Start a new session with these questions" }),
  ).toHaveAttribute("href", `/agents/${SESSION.agent_id}/improve/new?dataset=d9`);
  view.rerender(<TestQuestions session={SESSION} />);
  expect(screen.queryByText(/Too few questions/)).not.toBeInTheDocument();
});
it("asks for at least five questions however few are missing", () => {
  render(
    <TestQuestions
      session={{
        ...SESSION,
        iterations: [{ ...SESSION.iterations[0]!, verdict_detail: { missing_holdout: 1 } }],
      }}
    />,
  );
  expect(screen.getByRole("button", { name: "Write 5 more" })).toBeInTheDocument();
});
it("handles missing questions, their loading and a failed read", async () => {
  state.total = 0;
  state.questions = [];
  const view = render(<TestQuestions session={SESSION} />);
  expect(screen.getByText("0 test questions")).toBeInTheDocument();
  state.loading = true;
  view.rerender(<TestQuestions session={SESSION} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.loading = false;
  state.questionError = new Error("Forbidden");
  view.rerender(<TestQuestions session={SESSION} />);
  await userEvent.click(screen.getByRole("button", { name: "Try reading again" }));
  expect(state.refetch).toHaveBeenCalled();
});
it("waits for source counts instead of printing a missing response as zero", () => {
  state.sources = null;
  render(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.queryByText("0")).not.toBeInTheDocument();
});

it("explains a failed classifier while keeping source conversations visible", () => {
  render(
    <Understand
      session={{
        ...SESSION,
        timeline: [
          {
            action: "improvement.classification_failed",
            at: SESSION.created_at,
            stage: "classifying",
            status: "running",
            reason: null,
          },
        ],
      }}
    />,
  );
  expect(screen.getByText(/couldn’t finish grouping the feedback/)).toBeInTheDocument();
  expect(screen.getByText("Refund?")).toBeInTheDocument();
});

it("counts the test questions by where they came from and shows the answer to avoid", async () => {
  const question = (id: string, extra: object) => ({
    id,
    input: `Question ${id}`,
    improvement_partition: "holdout",
    reference_answer: null,
    counter_example: null,
    ...extra,
  });
  state.questions = [
    question("q1", { source: "conversation", counter_example: "90 days" }),
    question("q2", { source: "conversation", reference_answer: "30 days" }),
    question("q3", { source: "synthetic" }),
    question("q4", { source: "manual" }),
  ];
  state.total = 4;
  const view = render(<TestQuestions session={SESSION} />);
  expect(state.datasetHook).toHaveBeenCalledWith(SESSION.dataset_id, {
    version: SESSION.dataset_version,
    limit: 100,
  });
  expect(
    screen.getByRole("img", {
      name: "4 test questions: 1 from answers people rated down, 1 from answers they liked, 1 written for topics with no example, 1 added by hand or imported.",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText("From answers rated down").closest("li")).toHaveTextContent("1");
  await userEvent.click(screen.getByText("Review the questions"));
  expect(screen.getByText("An answer to avoid: 90 days")).toBeInTheDocument();
  expect(screen.getAllByText("Not used to write the changes")).toHaveLength(4);
  state.questions = state.questions.slice(0, 3);
  state.total = 3;
  view.rerender(<TestQuestions session={SESSION} />);
  expect(
    screen.getByRole("img", { name: /written for topics with no example\.$/ }),
  ).toBeInTheDocument();
});

function withTopic() {
  state.sources!.items.push({
    run_id: "r5",
    conversation_id: "c5",
    kind: "chat",
    status: "completed",
    rating: -1,
    question: "Shipping to Canada?",
    answer: "Unknown",
    comments: [],
    branch: "missing_knowledge",
    reason: null,
    topic_id: "t1",
  });
  state.sources!.items[2]!.topic_id = "t1";
}

it("groups examples by topic into problems and says how many each column holds", async () => {
  withTopic();
  state.sources!.items.push({
    ...state.sources!.items.at(-1)!,
    run_id: "r7",
    question: null,
    conversation_id: null,
  });
  render(<Understand session={SESSION} />);
  expect(
    screen.getByText(
      "We found 3 problems: 2 we can fix in the agent, 1 is information missing from the knowledge base.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("3 conversations about one topic")).toBeInTheDocument();
  await userEvent.click(screen.getByText("2 more conversations about this"));
  expect(screen.getByText("Shipping to Canada?")).toBeInTheDocument();
  expect(
    screen
      .getAllByRole("link", { name: "Open conversation" })
      .map((link) => link.getAttribute("href")),
  ).toContain("/chat/c5");
});

it("keeps answers whose knowledge was added since apart from what is still missing", async () => {
  withTopic();
  const added = {
    document_id: "doc1",
    filename: "shipping.md",
    knowledge_base_id: "kb1",
    added_at: "2026-10-27T07:52:00Z",
  };
  for (const item of state.sources!.items.filter((each) => each.topic_id === "t1"))
    item.knowledge_added = added;
  state.sources!.items.push({
    ...state.sources!.items.at(-1)!,
    run_id: "r8",
    question: "Gift cards?",
    topic_id: "t2",
    knowledge_added: { ...added, added_at: null },
  });
  render(<Understand session={SESSION} />);
  expect(
    screen.getByText(
      "We found 4 problems: 2 we can fix in the agent, 2 lacked knowledge that has since been added to the knowledge base.",
    ),
  ).toBeInTheDocument();
  const group = screen.getByRole("region", { name: "Already in the knowledge base" });
  expect(within(group).getByText(/Gift cards\?/)).toBeInTheDocument();
  expect(within(group).getByText(/Added Oct 27:/)).toBeInTheDocument();
  expect(within(group).getByText(/Added since:/)).toBeInTheDocument();
  expect(within(group).getAllByRole("link", { name: "shipping.md" })[0]).toHaveAttribute(
    "href",
    "/rag/kb1?tab=documents",
  );
  const missing = screen.getByRole("region", { name: "Missing from the knowledge base" });
  expect(within(missing).getByText("No selected examples in this group.")).toBeInTheDocument();
});

it("shows the examples to read, with nothing to ignore, put back or move", async () => {
  withTopic();
  render(<Understand session={SESSION} />);
  expect(screen.getByText("Refund?")).toBeInTheDocument();
  expect(screen.getByText("Deadline?")).toBeInTheDocument();
  await userEvent.click(screen.getByText("Refund?"));
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByText(/ignore it|Ignored \(/)).not.toBeInTheDocument();
});

it("says more questions are needed without offering to write them once only read", () => {
  const short = {
    ...SESSION,
    iterations: [{ ...SESSION.iterations[0]!, verdict_detail: { missing_holdout: 3 } }],
  };
  render(
    <ReadOnlyProvider value="finished">
      <TestQuestions session={short} />
    </ReadOnlyProvider>,
  );
  expect(screen.getByText(/Too few questions to measure a change/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Write \d+ more/ })).not.toBeInTheDocument();
});

it("shows the question set a new session would test on, and nothing until it is read", () => {
  state.total = 2;
  const view = render(<StartQuestionSet datasetId="d9" />);
  expect(state.datasetHook).toHaveBeenCalledWith("d9", { limit: 100 });
  expect(screen.getByRole("heading", { name: "2 test questions" })).toBeInTheDocument();
  expect(
    screen.getByRole("img", {
      name: /^Each attempt keeps about 1 question aside to check the result; about 1 helps write the changes\. A question also asked/,
    }),
  ).toBeInTheDocument();
  view.rerender(<StartQuestionSet datasetId="d9" heldOut={2} />);
  expect(
    screen.getByRole("img", {
      name: "The first attempt keeps 2 questions aside to check the result; 0 help write the changes, counting those also asked in the conversations it learns from.",
    }),
  ).toBeInTheDocument();
  state.total = 3;
  view.rerender(<StartQuestionSet datasetId="d9" />);
  expect(screen.getByRole("heading", { name: "3 test questions" })).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  state.loading = true;
  view.rerender(<StartQuestionSet datasetId="d9" />);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  state.loading = false;
  state.total = 0;
  view.rerender(<StartQuestionSet datasetId="d9" />);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
});

const GRADED = {
  run_id: "r6",
  conversation_id: null,
  kind: "train_eval" as const,
  status: "train_eval_failure",
  rating: 0,
  question: "  refund?  ",
  answer: "Sure, 90 days",
  comments: [],
  branch: "agent" as const,
  reason: null,
  grades: [
    {
      scorer: "judge" as const,
      name: "Follows the policy",
      status: "fail" as const,
      reason: "1/5: It promises 90 days",
    },
    { scorer: "check" as const, name: "regex '200'", status: "pass" as const, reason: "Matches" },
    {
      scorer: "judge" as const,
      name: "Polite",
      status: "error" as const,
      reason: "The judge could not be reached",
    },
  ],
};

it("shows a question asked both as a test and in a conversation as one problem", async () => {
  state.sources!.items.push(GRADED);
  render(<Understand session={SESSION} />);
  expect(
    screen.getByText(
      "We found 3 problems: 2 we can fix in the agent, 1 is information missing from the knowledge base.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Test question and conversation example")).toBeInTheDocument();
  expect(screen.queryByText(/more conversations? about this/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("Refund?"));
  expect(
    screen.getByText("The judge gave 1/5 for “Follows the policy”: It promises 90 days"),
  ).toBeInTheDocument();
  expect(screen.getByText("Rule “regex '200'”: met")).toBeInTheDocument();
  expect(
    screen.getByText("The judge on “Polite”: The judge could not be reached"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Its test answer failed “Follows the policy” (1/5)."),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "Open conversation" })[0]).toHaveAttribute(
    "href",
    "/chat/c1",
  );
});

it("says why from what each example holds, and falls back when it holds nothing", async () => {
  state.sources!.items = [
    {
      ...GRADED,
      question: "Deadline?",
      grades: [{ scorer: "check", name: "length", status: "fail", reason: "900 words" }],
    },
    {
      ...state.sources!.items[0]!,
      run_id: "r9",
      question: "Crashed?",
      status: "failed",
      comments: [],
      branch: "agent",
    },
    {
      ...state.sources!.items[0]!,
      run_id: "r10",
      question: "Quiet?",
      comments: [],
      branch: "agent",
    },
    {
      ...state.sources!.items[0]!,
      run_id: "r11",
      question: "Unrated?",
      rating: 0,
      branch: "agent",
    },
    { ...GRADED, run_id: "r12", question: "Noted?", grades: undefined },
  ];
  render(<Understand session={SESSION} />);
  for (const question of ["Deadline?", "Crashed?", "Quiet?", "Unrated?", "Noted?"])
    await userEvent.click(screen.getByText(question));
  expect(screen.getByText("Its test answer failed “length”.")).toBeInTheDocument();
  expect(screen.getByText("Rule “length”: not met")).toBeInTheDocument();
  expect(screen.getByText("The agent did not finish this answer.")).toBeInTheDocument();
  expect(
    screen.getByText("A person rated this answer down, without a comment."),
  ).toBeInTheDocument();
  expect(screen.getByText(/existing feedback and classification/)).toBeInTheDocument();
  expect(screen.getByText(/test answer failed or has a review note/)).toBeInTheDocument();
});

it("counts what the newest attempt is measured on, and about the share before", () => {
  state.total = 2;
  const checked = {
    ...SESSION,
    iterations: [
      { ...SESSION.iterations[0]!, held_out: 2 },
      { ...SESSION.iterations[0]!, number: 2, held_out: null },
    ],
  };
  const view = render(<TestQuestions session={checked} />);
  expect(
    screen.getByRole("img", {
      name: "Attempt 1 kept 2 questions aside to check the result; 0 helped write the changes.",
    }),
  ).toBeInTheDocument();
  state.share = undefined;
  view.rerender(<TestQuestions session={SESSION} />);
  expect(
    screen.getByRole("img", { name: /^Each attempt keeps about 1 question aside/ }),
  ).toBeInTheDocument();
});
