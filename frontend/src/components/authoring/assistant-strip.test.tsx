import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/agents/improve-link", () => ({
  ImproveButton: ({ agentId }: { agentId: string }) => <button>Improve {agentId}</button>,
}));
import { agentAuthoring, authoringRequest, batch, hunk } from "@/test-utils/authoring";
import { evalRun } from "@/test-utils/eval-runs";
import type { AgentAuthoring } from "@/types/authoring";
import type { AgentSpec } from "@/types/agents";
import { AssistantStrip } from "./assistant-strip";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  // The suggestions keep their tab in `?suggestions=`.
  useSearchParams: () => new URLSearchParams(),
}));
const toastError = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({ toast: { error: toastError, success: toastSuccess } }));

const state = vi.hoisted(() => ({
  authoring: null as AgentAuthoring | null,
  enabled: true as boolean | null,
  runsView: true,
  skillsEdit: true,
  createSkill: vi.fn(),
  published: undefined as { spec: unknown } | undefined,
  decide: vi.fn(),
  dismissAll: vi.fn(),
  decideIdea: vi.fn(),
  isLoading: false,
  error: null as Error | null,
}));
vi.mock("@/hooks/use-organizations", () => ({
  useAiAssistance: () => ({ orgId: "org-1", enabled: state.enabled }),
}));
vi.mock("@/hooks", () => ({
  useDraftBase: () => ({ base: state.published }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (perm: string) => (perm === "skills:edit" ? state.skillsEdit : state.runsView),
  }),
}));
vi.mock("@/hooks/use-eval-suites", () => ({ useAgentEvalSuites: () => ({ suites: [] }) }));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEveryDataset: () => ({ datasets: [{ id: "ds-1", name: "Refund cases" }] }),
  useEveryAgent: () => ({ agents: [] }),
}));
vi.mock("@/components/evals/estimate-summary", () => ({ EstimateSummary: () => <p>priced</p> }));
vi.mock("@/hooks/use-authoring", () => ({
  useAgentAuthoring: () => ({
    authoring: state.authoring,
    isLoading: state.isLoading,
    error: state.error,
    estimate: {
      mutateAsync: vi.fn().mockResolvedValue({
        runs: 1,
        rated_down: 1,
        calls: 1,
        estimate_usd: "0.01",
        affordable: true,
        reason: null,
      }),
    },
    start: { mutateAsync: vi.fn() },
    decide: { mutateAsync: state.decide, isPending: false },
    createSkill: { mutateAsync: state.createSkill },
    decideIdea: { mutate: state.decideIdea, isPending: false },
    dismissAll: { mutate: state.dismissAll, isPending: false },
    checkEstimate: { mutateAsync: CHECK_ESTIMATE },
    check: { mutateAsync: vi.fn().mockResolvedValue(evalRun({ id: "eval-9" })) },
  }),
}));

const CHECK_ESTIMATE = vi.hoisted(
  () => () => Promise.resolve({ total_usd: "0.10", affordable: true }),
);

const DRAFT = { name: "Clerk", instructions: "Be brief." } as AgentSpec;

function strip(persist = vi.fn().mockResolvedValue(true), onDraft = vi.fn()) {
  render(
    <AssistantStrip
      agentId="agent-1"
      storedDraft={DRAFT}
      canCheck
      persist={persist}
      onDraft={onDraft}
    />,
  );
  return { persist, onDraft };
}

beforeEach(() => {
  state.runsView = true;
  state.skillsEdit = true;
  state.createSkill = vi.fn();
  state.authoring = agentAuthoring();
  state.enabled = true;
  state.published = { spec: DRAFT };
  state.decide = vi.fn();
  state.dismissAll = vi.fn();
  state.isLoading = false;
  state.error = null;
  push.mockReset();
  toastError.mockReset();
  toastSuccess.mockReset();
});

const IDEA = {
  proposed: 1,
  recorded: 0,
  rejected: [
    {
      kind: "create_skill" as const,
      reason: "insufficient_evidence" as const,
      change: {
        name: "Refund Policy",
        description: "Explain refunds",
        content: "Ask for the order first.",
        answers: 2,
      },
    },
  ],
};

describe("AssistantStrip", () => {
  it("says what waits and where it came from", () => {
    strip();
    expect(
      screen.getByText("1 suggestion · from 6 rated-down answers across 22 runs"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify my edits" })).toBeNull();
  });

  it("lets the line about what waits wrap on a phone", () => {
    strip();
    expect(screen.getByText("1 suggestion · from 6 rated-down answers across 22 runs")).toHaveClass(
      "whitespace-normal",
    );
  });

  it("counts what waits even when the request said nothing about its evidence", () => {
    state.authoring = agentAuthoring({ latest: authoringRequest({ evidence: {} }) });
    strip();
    expect(
      screen.getByText("1 suggestion · from 0 rated-down answers across 0 runs"),
    ).toBeInTheDocument();
  });

  it("stores the page's draft before a decision and adopts the draft it wrote", async () => {
    const written = { name: "Clerk", instructions: "Be brief. Refunds take 30 days." };
    state.decide.mockResolvedValue({ authoring: agentAuthoring(), draft_spec: written });
    const { persist, onDraft } = strip();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(persist).toHaveBeenCalled();
    expect(state.decide).toHaveBeenCalledWith({ hunkId: "hunk-1", action: "accept" });
    await waitFor(() => expect(onDraft).toHaveBeenCalledWith(written));
  });

  it("decides nothing when the draft did not store, and toasts a refused decision", async () => {
    const { onDraft } = strip(vi.fn().mockResolvedValue(false));
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(state.decide).not.toHaveBeenCalled();
    expect(onDraft).not.toHaveBeenCalled();
  });

  it("toasts a decision the server refused", async () => {
    state.decide.mockRejectedValue(new Error("No longer fits"));
    strip();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("No longer fits"));
  });

  it("offers Verify once the draft differs, and Improve as the wizard's own button", async () => {
    state.published = { spec: { ...DRAFT, instructions: "Old." } };
    strip();
    await userEvent.click(screen.getByRole("button", { name: "Verify my edits" }));
    expect(await screen.findByRole("heading", { name: "Verify your edits" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Improve agent-1" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Improve this agent" })).toBeNull();
  });

  it("dismisses everything waiting and opens the check", async () => {
    strip();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss all" }));
    expect(state.dismissAll).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Check with evals" }));
    expect(await screen.findByRole("heading", { name: "Check with evals" })).toBeInTheDocument();
  });

  it("says a check with evals needs runs:view to somebody who may not read runs", async () => {
    state.runsView = false;
    const { rerender } = render(
      <AssistantStrip
        agentId="agent-1"
        storedDraft={DRAFT}
        canCheck={false}
        checkNeedsRunsView
        persist={vi.fn()}
        onDraft={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /^Improve/ })).toBeNull();
    const check = screen.getByRole("button", { name: /Check with evals/ });
    expect(check).toHaveAttribute("aria-disabled", "true");
    expect(check).toHaveAttribute("title", "Needs permission to read runs");
    await userEvent.click(check);
    expect(screen.queryByRole("heading", { name: "Check with evals" })).toBeNull();

    // Nothing to run a check on either: reading runs would not be enough, so no reason is given.
    rerender(
      <AssistantStrip
        agentId="agent-1"
        storedDraft={DRAFT}
        canCheck={false}
        persist={vi.fn()}
        onDraft={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /Check with evals/ })).toBeNull();
  });

  it("offers no new request until it knows whether one is already at work", () => {
    state.published = { spec: { ...DRAFT, instructions: "Old." } };
    state.isLoading = true;
    const { unmount } = render(
      <AssistantStrip
        agentId="agent-1"
        storedDraft={DRAFT}
        canCheck
        persist={vi.fn()}
        onDraft={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Verify my edits" })).toBeDisabled();
    unmount();

    state.isLoading = false;
    state.error = new Error("502");
    state.published = { spec: { ...DRAFT, instructions: "Old." } };
    strip();
    expect(screen.getByRole("button", { name: "Verify my edits" })).toBeDisabled();
  });

  it("is visibly off, with the way to turn it on, while AI assistance is", () => {
    state.enabled = false;
    state.published = { spec: { ...DRAFT, instructions: "Old." } };
    strip();
    expect(screen.getByRole("button", { name: "Verify my edits" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Turn it on" })).toBeInTheDocument();
  });

  it("shows a request at work, a failed one, and the verify report", () => {
    state.authoring = agentAuthoring({
      batch: null,
      latest: authoringRequest({ status: "running" }),
      verify: authoringRequest({
        kind: "verify",
        report: {
          findings: [{ verdict: "risk", text: "Risky", evidence: [], evidence_dropped: 0 }],
        },
      }),
    });
    const { unmount } = (() => {
      const result = render(
        <AssistantStrip
          agentId="agent-1"
          storedDraft={DRAFT}
          canCheck
          persist={vi.fn()}
          onDraft={vi.fn()}
        />,
      );
      return result;
    })();
    expect(screen.getByRole("status")).toHaveTextContent("Reading the runs…");
    expect(screen.getByText("What the assistant made of your edits")).toBeInTheDocument();
    unmount();
    state.authoring = agentAuthoring({
      batch: null,
      latest: authoringRequest({ status: "failed", error: "Nothing to learn from yet." }),
    });
    strip();
    expect(screen.getByRole("alert")).toHaveTextContent("Nothing to learn from yet.");
  });

  it("explains itself before it was ever asked, and hides the batch actions of a closed batch", () => {
    state.authoring = null;
    const { unmount } = render(
      <AssistantStrip
        agentId="agent-1"
        storedDraft={DRAFT}
        canCheck
        persist={vi.fn()}
        onDraft={vi.fn()}
      />,
    );
    expect(screen.getByText(/The assistant reads what people rated down/)).toBeInTheDocument();
    unmount();
    state.authoring = agentAuthoring({
      batch: batch({ status: "published", hunks: [hunk({ status: "accepted" })] }),
      latest: authoringRequest({ evidence: {} }),
    });
    strip();
    expect(screen.queryByRole("button", { name: "Dismiss all" })).toBeNull();
  });

  it("says which proposed changes the last request could not record", () => {
    state.authoring = agentAuthoring({
      latest: authoringRequest({
        report: {
          proposed: 1,
          recorded: 0,
          rejected: [
            {
              kind: "instructions",
              reason: "unanchored",
              change: { old_text: "Refunds take 90 days.", new_text: "Refunds take 30 days." },
            },
          ],
        },
      }),
    });
    strip();
    expect(screen.getByText("1 more idea the assistant did not add")).toBeInTheDocument();
  });

  it("goes to the eval run a check started", async () => {
    strip();
    await userEvent.click(screen.getByRole("button", { name: "Check with evals" }));
    await userEvent.click(await screen.findByRole("combobox", { name: "Check against" }));
    await userEvent.click(await screen.findByRole("option", { name: "Refund cases" }));
    await screen.findByText("priced");
    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/agents/agent-1/evals/eval-9"));
  });

  it("creates a skill idea it did not add, after the page's draft is stored", async () => {
    const written = { ...DRAFT, skill_ids: ["skill-9"] };
    state.createSkill.mockResolvedValue({ authoring: agentAuthoring(), draft_spec: written });
    state.authoring = agentAuthoring({ latest: authoringRequest({ report: IDEA }) });
    const { persist, onDraft } = strip();
    expect(screen.queryByText("1 more idea needs your decision")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Create skill" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/^Based on 2 answers\./)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Create skill" }));
    expect(persist).toHaveBeenCalled();
    expect(state.createSkill).toHaveBeenCalledWith({
      requestId: "request-1",
      index: 0,
      name: "refund-policy",
      description: "Explain refunds",
      content: "Ask for the order first.",
    });
    await waitFor(() => expect(onDraft).toHaveBeenCalledWith(written));
    expect(toastSuccess).toHaveBeenCalledWith("Skill refund-policy created and added to the draft");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("creates nothing while the page's draft cannot be stored", async () => {
    state.authoring = agentAuthoring({ latest: authoringRequest({ report: IDEA }) });
    strip(vi.fn().mockResolvedValue(false));
    await userEvent.click(screen.getByRole("button", { name: "Create skill" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create skill" }));
    expect(state.createSkill).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("creates a skill idea from the result dialog too", async () => {
    state.createSkill.mockResolvedValue({ authoring: agentAuthoring(), draft_spec: DRAFT });
    state.authoring = agentAuthoring({ latest: authoringRequest({ report: IDEA }) });
    strip();
    await userEvent.click(screen.getByRole("button", { name: "Review result" }));
    const result = await screen.findByRole("dialog");
    await userEvent.click(within(result).getByRole("button", { name: "Create skill" }));
    const preview = screen.getAllByRole("dialog").at(-1)!;
    await userEvent.click(within(preview).getByRole("button", { name: "Create skill" }));
    await waitFor(() =>
      expect(state.createSkill).toHaveBeenCalledWith(
        expect.objectContaining({ requestId: "request-1", index: 0 }),
      ),
    );
  });

  it("offers no skill to someone who may not create skills, but lets them dismiss it", () => {
    state.skillsEdit = false;
    state.authoring = agentAuthoring({ latest: authoringRequest({ report: IDEA }) });
    strip();
    expect(screen.getByTestId("idea")).toHaveTextContent("Refund Policy");
    expect(screen.queryByRole("button", { name: "Create skill" })).toBeNull();
    expect(
      within(screen.getByTestId("idea")).getByRole("button", { name: "Dismiss" }),
    ).toBeEnabled();
  });

  it("dismisses an idea on its request, and toasts a refused dismissal", async () => {
    state.authoring = agentAuthoring({ batch: null, latest: authoringRequest({ report: IDEA }) });
    strip();
    await userEvent.click(
      within(screen.getByTestId("idea")).getByRole("button", { name: "Dismiss" }),
    );
    expect(state.decideIdea).toHaveBeenCalledWith(
      { requestId: "request-1", index: 0, action: "dismiss" },
      expect.objectContaining({ onError: expect.any(Function) }),
    );
    const [, options] = state.decideIdea.mock.calls[0]!;
    options.onError(new Error("refused"));
    expect(toastError).toHaveBeenCalled();
  });
});

it("keeps the assistant to one line for an agent without learning evidence", () => {
  state.authoring = agentAuthoring({
    batch: null,
    latest: null,
    verify: null,
    has_evidence: false,
  });
  strip();
  expect(screen.getByRole("button", { name: "Improve agent-1" })).toBeInTheDocument();
  expect(screen.queryByText("No suggestions yet")).not.toBeInTheDocument();
  expect(screen.queryByTestId("suggestion")).not.toBeInTheDocument();
});
