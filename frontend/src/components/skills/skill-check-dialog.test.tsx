import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillCheckDialog } from "./skill-check-dialog";
import { ApiError } from "@/lib/api-error";
import { finishedCheck } from "@/test-utils/skill-checks";
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
  estimate: {} as Mutation,
  start: {} as Mutation,
  apply: {} as Mutation,
  discard: {} as Mutation,
  cancel: {} as Mutation,
  checkId: null as string | null,
}));

vi.mock("@/hooks/use-skill-check", () => ({
  useSkillCheck: (_skillId: string, checkId: string | null) => {
    held.checkId = checkId;
    return held;
  },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

function mutation(overrides: Partial<Mutation> = {}): Mutation {
  return { mutate: vi.fn(), isPending: false, isError: false, error: null, ...overrides };
}

beforeEach(() => {
  held.check = null;
  held.estimate = mutation({ data: finishedCheck() });
  held.start = mutation();
  held.apply = mutation();
  held.discard = mutation();
  held.cancel = mutation();
});

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
    expect(screen.getByText(/Most likely \$0.08, at most \$0.24/)).toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("closes once discarded, and stays open when applying is refused", async () => {
    held.check = finishedCheck();
    held.apply.mutate.mockImplementation((_body, options) => options.onError(new Error("moved")));
    held.discard.mutate.mockImplementation((_body, options) => options.onSuccess());
    const onOpenChange = open();

    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onOpenChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes once a finished check is applied or discarded", async () => {
    held.check = finishedCheck();
    held.apply.mutate.mockImplementation((_body, options) => options.onSuccess());
    held.discard.mutate.mockImplementation((_body, options) => options.onError(new Error("gone")));
    const onOpenChange = open();

    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onOpenChange).toHaveBeenCalledTimes(1);
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
        change={{ candidate: { description: "Returns.", content: "Refund within 14 days." } }}
        forkId="f-1"
        onOpenChange={onOpenChange}
        onApplied={onApplied}
      />,
    );

    expect(held.estimate.mutate).toHaveBeenCalledWith({
      fork_id: "f-1",
      candidate: { description: "Returns.", content: "Refund within 14 days." },
    });
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApplied).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
