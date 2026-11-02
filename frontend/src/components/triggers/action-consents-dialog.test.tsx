import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ActionConsentsDialog } from "./action-consents-dialog";
import type { Trigger } from "@/types/triggers";

const state = vi.hoisted(() => ({
  data: {
    can_waive: true,
    review_token: "review-1",
    items: [
      {
        capability_id: "sandbox",
        tool_id: "execute",
        name: "execute",
        consented: false,
        waivable: true,
      },
      {
        capability_id: "other",
        tool_id: "publish",
        name: "publish",
        consented: false,
        waivable: false,
      },
    ],
  },
  error: null as Error | null,
  save: vi.fn(),
  retry: vi.fn(),
}));
vi.mock("@/hooks/use-routine-actions", () => ({
  useRoutineActions: () => ({
    data: state.data,
    isLoading: false,
    error: state.error,
    replace: { mutate: state.save, isPending: false },
    refetch: state.retry,
  }),
}));
const trigger = { id: "routine", agent_id: "agent" } as Trigger;

describe("routine action consent", () => {
  beforeEach(() => {
    state.save.mockReset();
    state.error = null;
    state.data.can_waive = true;
    state.data.review_token = "review-1";
  });
  it("submits only explicitly selected action identities and preserves required gates", async () => {
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "publish" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "execute" }));
    await userEvent.click(screen.getByRole("button", { name: "Save consent" }));
    expect(state.save).toHaveBeenCalledWith(
      [{ capability_id: "sandbox", tool_id: "execute" }],
      expect.any(Object),
    );
  });
  it("can revoke all while organization policy disallows new consent", async () => {
    state.data.can_waive = false;
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "execute" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Revoke all" }));
    expect(state.save).toHaveBeenCalledWith([], expect.any(Object));
  });
  it("drops a selection when a refreshed review describes a different version", async () => {
    const close = vi.fn();
    const { rerender } = render(<ActionConsentsDialog trigger={trigger} onClose={close} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "execute" }));
    state.data.review_token = "review-2";
    rerender(<ActionConsentsDialog trigger={trigger} onClose={close} />);
    expect(screen.getByRole("checkbox", { name: "execute" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Save consent" }));
    expect(state.save).toHaveBeenCalledWith([], expect.any(Object));
  });
  it("shows a fetch failure and cannot save it as empty consent", () => {
    state.error = new Error("offline");
    render(<ActionConsentsDialog trigger={trigger} onClose={vi.fn()} />);
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save consent" })).toBeDisabled();
  });
});
