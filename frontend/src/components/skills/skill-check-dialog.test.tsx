import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillCheckDialog } from "./skill-check-dialog";
import { ApiError } from "@/lib/api-error";
import { checkAgent, finishedCheck } from "@/test-utils/skill-checks";
import type { SkillCheck } from "@/types/skill-checks";

type Mutation = {
  mutate: ReturnType<typeof vi.fn>;
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data?: unknown;
};

const held = vi.hoisted(() => ({
  check: null as SkillCheck | null,
  reading: { isLoading: false, error: null as unknown },
  estimate: {} as Mutation,
  start: {} as Mutation,
  apply: {} as Mutation,
  discard: {} as Mutation,
  cancel: {} as Mutation,
  fork: {} as Mutation & { mutateAsync: ReturnType<typeof vi.fn> },
  checkId: null as string | null,
}));

const permissions = vi.hoisted(() => ({ datasetsEdit: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => permissions.datasetsEdit, isLoading: false }),
}));

vi.mock("@/hooks/use-skill-check", () => ({
  useSkillCheck: (_skillId: string, checkId: string | null) => {
    held.checkId = checkId;
    return held;
  },
  useSkillTestSet: () => ({
    testSet: null,
    isLoading: false,
    error: null,
    create: {
      mutate: (_body: unknown, options?: { onSuccess?: () => void }) => options?.onSuccess?.(),
    },
  }),
}));
vi.mock("@/hooks/use-skill-versions", () => ({
  useSkillAgents: () => ({ agents: { items: [] }, error: null, retry: vi.fn(), retrying: false }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

function mutation(overrides: Partial<Mutation> = {}): Mutation {
  return { mutate: vi.fn(), isPending: false, isError: false, error: null, ...overrides };
}

beforeEach(() => {
  held.check = null;
  held.reading = { isLoading: false, error: null };
  held.estimate = mutation({ data: finishedCheck() });
  held.start = mutation();
  held.apply = mutation();
  held.discard = mutation();
  held.cancel = mutation();
  held.fork = { ...mutation(), mutateAsync: vi.fn() };
});

async function discard() {
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  const confirm = screen.getAllByRole("dialog").at(-1)!;
  await userEvent.click(within(confirm).getByRole("button", { name: "Discard" }));
}

function open(onOpenChange = vi.fn()) {
  render(
    <SkillCheckDialog
      skillId="s-1"
      change={{ proposalId: "p-1" }}
      forkId={null}
      onOpenChange={onOpenChange}
    />,
  );
  return onOpenChange;
}

describe("SkillCheckDialog", () => {
  it("prices the check on opening and starts it on request", async () => {
    held.start.mutate.mockImplementation((_body, options) => options.onSuccess({ id: "c-9" }));
    open();

    expect(held.estimate.mutate).toHaveBeenCalledWith({ fork_id: null, proposal_id: "p-1" });
    expect(screen.getByText(/Most likely \$0.0800, at most \$0.2400\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));

    expect(held.checkId).toBe("c-9");
  });

  it("says why a check that could not start did not", async () => {
    held.start.mutate.mockImplementation((_body, options) => options.onError(new Error("budget")));
    open();

    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));

    expect(held.checkId).toBeNull();
  });

  it("goes back to the check the server says this change already has", async () => {
    held.start.mutate.mockImplementation((_body, options) =>
      options.onError(
        new ApiError(409, "This change is checked already", {
          error: { code: "ALREADY_EXISTS", message: "checked", details: { check_id: "c-open" } },
        }),
      ),
    );
    open();

    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));

    expect(held.checkId).toBe("c-open");
  });

  it("stops a running check on request", async () => {
    held.check = finishedCheck({ status: "running", verdict: null, outcomes: [] });
    held.cancel.mutate.mockImplementation((_body, options) => options.onSuccess());
    const onOpenChange = open();

    await userEvent.click(screen.getByRole("button", { name: "Stop the check" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("says why a check the organization cannot afford cannot start", () => {
    held.estimate = mutation({ data: finishedCheck({ affordable: false }) });
    open();

    expect(screen.getByText(/budget left this month cannot cover/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start the check" })).toBeDisabled();
  });

  it("says why the check cannot be priced", () => {
    held.estimate = mutation({ isError: true, error: new Error("No agent can be checked") });
    open();

    expect(screen.getByText("No agent can be checked")).toBeInTheDocument();
  });

  it("shows a running check without a decision", () => {
    held.check = finishedCheck({ status: "running", verdict: null, outcomes: [] });
    open();

    expect(screen.getByText(/Checking\. This takes a few minutes/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "the skill's page" })).toHaveAttribute(
      "href",
      "/skills/s-1",
    );
    expect(screen.getByRole("progressbar", { name: "Agents checked" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("opens a check left running again, without pricing it anew", () => {
    held.check = finishedCheck({ status: "running", verdict: null, outcomes: [] });
    render(<SkillCheckDialog skillId="s-1" resume="c-9" forkId={null} onOpenChange={vi.fn()} />);

    expect(held.checkId).toBe("c-9");
    expect(held.estimate.mutate).not.toHaveBeenCalled();
    expect(screen.getByText(/Checking\. This takes a few minutes/)).toBeInTheDocument();
  });

  it("says a check opened again is being read, and why it could not be", () => {
    held.reading = { isLoading: true, error: null };
    const { rerender } = render(
      <SkillCheckDialog skillId="s-1" resume="c-9" forkId={null} onOpenChange={vi.fn()} />,
    );
    expect(screen.getByRole("dialog").querySelector(".animate-pulse")).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    held.reading = {
      isLoading: false,
      error: new ApiError(404, "Check not found", {
        error: { code: "NOT_FOUND", message: "Check not found" },
      }),
    };
    rerender(<SkillCheckDialog skillId="s-1" resume="c-9" forkId={null} onOpenChange={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Check not found");
    expect(screen.getByRole("dialog").querySelector(".animate-pulse")).toBeNull();
  });

  it("shows a check without stopping or deciding it to a reader who may not decide", () => {
    held.check = finishedCheck({ status: "running", verdict: null, outcomes: [] });
    const { rerender } = render(
      <SkillCheckDialog
        skillId="s-1"
        resume="c-9"
        forkId={null}
        canDecide={false}
        onOpenChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/Checking\. This takes a few minutes/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop the check" })).toBeNull();

    held.check = finishedCheck();
    rerender(
      <SkillCheckDialog
        skillId="s-1"
        resume="c-9"
        forkId={null}
        canDecide={false}
        onOpenChange={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();
  });

  it("closes once discarded, and stays open when applying is refused", async () => {
    held.check = finishedCheck();
    held.apply.mutate.mockImplementation((_body, options) => options.onError(new Error("moved")));
    held.discard.mutate.mockImplementation((_body, options) => options.onSuccess());
    const onOpenChange = open();

    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onOpenChange).not.toHaveBeenCalled();
    await discard();

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes once a finished check is applied or discarded", async () => {
    held.check = finishedCheck();
    held.apply.mutate.mockImplementation((_body, options) => options.onSuccess());
    held.discard.mutate.mockImplementation((_body, options) => options.onError(new Error("gone")));
    const onOpenChange = open();

    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await discard();

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onOpenChange).toHaveBeenCalledTimes(1);
  });

  it("leaves a check made to move one agent to Change version on that agent", () => {
    held.check = finishedCheck({ source: "catch_up" });
    open();

    expect(screen.getByText(/Decide it from Change version/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();
  });

  it("points a check an improvement session started to that session", () => {
    held.check = finishedCheck({ session_id: "sess-1" });
    open();

    expect(screen.getByText(/decided there/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the session" })).toHaveAttribute(
      "href",
      "/skills/s-1/improve/sess-1",
    );
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();
  });

  it("points to the session the server names when deciding here is refused", async () => {
    held.check = finishedCheck();
    held.apply.mutate.mockImplementation((_body, options) =>
      options.onError(
        new ApiError(409, "Decide in the session", {
          error: {
            code: "DECIDE_IN_SESSION",
            message: "Decide in the session",
            details: { session_id: "sess-2" },
          },
        }),
      ),
    );
    open();

    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(screen.getByRole("link", { name: "Open the session" })).toHaveAttribute(
      "href",
      "/skills/s-1/improve/sess-2",
    );
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("checks a text the editor has not saved, and says when it went live", async () => {
    held.check = finishedCheck();
    held.apply.mutate.mockImplementation((_body, options) => options.onSuccess());
    const onApplied = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <SkillCheckDialog
        skillId="s-1"
        change={{
          candidate: { description: "Returns.", content: "Refund within 14 days." },
          baseVersionId: "m12",
        }}
        forkId="f-1"
        onOpenChange={onOpenChange}
        onApplied={onApplied}
      />,
    );

    expect(held.estimate.mutate).toHaveBeenCalledWith({
      fork_id: "f-1",
      candidate: { description: "Returns.", content: "Refund within 14 days." },
      base_version_id: "m12",
    });
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApplied).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("hands a line that moved past the text back to the editor", async () => {
    const moved = new ApiError(409, "Moved", {
      error: { code: "CONCURRENT_CHANGE", message: "Moved", details: { version: 13 } },
    });
    held.estimate = mutation({ data: finishedCheck(), error: moved, isError: true });
    held.start.mutate.mockImplementation((_body, options) => options.onError(moved));
    const onLineMoved = vi.fn();
    render(
      <SkillCheckDialog
        skillId="s-1"
        change={{ candidate: { description: "Returns.", content: "Body" }, baseVersionId: "m12" }}
        forkId={null}
        onOpenChange={vi.fn()}
        onLineMoved={onLineMoved}
      />,
    );

    expect(onLineMoved).toHaveBeenCalledTimes(1);
    held.estimate = mutation({ data: finishedCheck() });
    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));
    expect(onLineMoved).toHaveBeenCalledTimes(2);
  });

  it("names what each agent fixed and broke once the check is done", async () => {
    held.check = finishedCheck({
      agents: [checkAgent({ name: "Web shop", state: "better", fixed: 1, broken: 0 })],
    });
    open();

    await userEvent.click(screen.getByRole("button", { name: "Details of Web shop" }));

    expect(screen.getByText("Fixes 1 question, breaks 0.")).toBeInTheDocument();
  });

  it("says nobody can be checked before it starts, and offers the questions and a way on", async () => {
    const unknown = { state: "unknown" as const, unknown_reason: "no_questions" as const };
    held.estimate = mutation({
      data: finishedCheck({
        agents: [checkAgent({ name: "A", ...unknown }), checkAgent({ name: "B", ...unknown })],
        expected_usd: "0",
        at_most_usd: "0",
      }),
    });
    held.start.mutate.mockImplementation((_body, options) => options.onSuccess({ id: "c-ack" }));
    open();

    expect(screen.getByText(/None of these agents can be checked/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add test questions" })).toBeInTheDocument();
    expect(screen.queryByText(/Most likely/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Go on without a check" }));

    expect(held.checkId).toBe("c-ack");
  });

  it("goes back to editing the checked text", async () => {
    held.check = finishedCheck({
      verdict: "no_better",
      outcomes: ["improve_further", "fork_for_helped", "discard"],
    });
    const onEdit = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <SkillCheckDialog
        skillId="s-1"
        resume="c-1"
        forkId={null}
        onOpenChange={onOpenChange}
        onEdit={onEdit}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Back to editing" }));

    expect(onEdit).toHaveBeenCalledWith({
      description: "Refunds",
      content: "Refund within 30 days.",
      baseVersionId: "v-3",
      forkId: null,
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes once the fork is made, and keeps a refused fork's reason in the fork dialog", async () => {
    held.check = finishedCheck({
      verdict: "no_better",
      outcomes: ["improve_further", "fork_for_helped", "discard"],
    });
    held.fork.mutateAsync.mockRejectedValueOnce(new Error("Name taken")).mockResolvedValueOnce({});
    const onApplied = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <SkillCheckDialog
        skillId="s-1"
        resume="c-1"
        forkId={null}
        onOpenChange={onOpenChange}
        onApplied={onApplied}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));
    await userEvent.click(screen.getByRole("button", { name: /Make the fork/ }));
    expect(await screen.findByText("Name taken")).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Make the fork/ }));

    expect(onApplied).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("says nobody reads the line before it starts, and that nobody was checked after", () => {
    held.estimate = mutation({
      data: finishedCheck({ agents: [], hidden: 0, expected_usd: "0", at_most_usd: "0" }),
    });
    open();

    expect(screen.getByText(/No agent reads this line, so there is nobody to check/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Go on without a check" })).toBeEnabled();
    expect(screen.queryByRole("list")).toBeNull();
    cleanup();

    held.check = finishedCheck({ agents: [], no_readers: true });
    open();
    expect(
      screen.getByText("No agent reads this line, so there was nobody to check."),
    ).toBeVisible();
  });

  it("prices the check again once test questions were written, and offers grading where it lacks", async () => {
    const agent = (name: string, reason: "unscorable" | "all_evidence") =>
      checkAgent({ name, state: "unknown", unknown_reason: reason });
    held.estimate = mutation({
      data: finishedCheck({ agents: [agent("A", "all_evidence"), agent("B", "unscorable")] }),
    });
    open();

    expect(screen.getByRole("link", { name: "Set up grading on Skill set" })).toHaveAttribute(
      "href",
      "/datasets/d-1?tab=grading",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add test questions" }));

    expect(held.estimate.mutate).toHaveBeenCalledTimes(2);
  });
});
