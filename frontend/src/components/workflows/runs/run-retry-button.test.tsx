import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore, useOrgStore } from "@/stores";

import { RunRetryButton } from "./run-retry-button";

const USER = {
  id: "account-a",
  email: "a@example.invalid",
  is_active: true,
  created_at: "2026-11-16T00:00:00Z",
};

beforeEach(() => {
  useAuthStore.setState({
    user: USER,
    sessionOwnerId: USER.id,
    isAuthenticated: true,
    impersonationRevoked: false,
  });
  useOrgStore.setState({ activeOrgId: "org-a", refusedOrgIds: [] });
});

function mount(hasMedia: boolean | null = true, busy = false) {
  const onRetry = vi.fn();
  return {
    onRetry,
    ...render(<RunRetryButton runId="run-a" hasMedia={hasMedia} busy={busy} onRetry={onRetry} />),
  };
}

describe("whole-run media retry", () => {
  it("retains the existing immediate action for a graph without media generation", async () => {
    const { onRetry } = mount(false);
    await userEvent.click(screen.getByRole("button"));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([
    [null, false],
    [false, true],
    [true, true],
  ] as const)("waits for a known graph and an idle action (%s, %s)", async (hasMedia, busy) => {
    const { onRetry } = mount(hasMedia, busy);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("requires a fresh charge acknowledgement and sends one deliberate retry", async () => {
    const { onRetry } = mount();
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This starts a new run and may generate media again, creating another provider charge. Earlier unresolved charges remain reserved.",
      ),
    ).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Start the new run" });
    expect(confirm).toBeDisabled();
    await userEvent.click(confirm);
    expect(onRetry).not.toHaveBeenCalled();
    const acknowledgement = screen.getByRole("checkbox", {
      name: "I understand this can create another provider charge.",
    });
    await userEvent.click(acknowledgement);
    await userEvent.click(acknowledgement);
    expect(confirm).toBeDisabled();
    await userEvent.click(acknowledgement);
    await userEvent.dblClick(confirm);
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button", { name: "Start the new run" })).toBeDisabled();
  });

  it("cancellation and Escape both forget an acknowledgement", async () => {
    const { onRetry } = mount();
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("disables a reviewed confirmation if an action becomes busy", async () => {
    const { onRetry, rerender } = mount();
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByRole("checkbox"));
    rerender(<RunRetryButton runId="run-a" hasMedia busy onRetry={onRetry} />);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start the new run" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Start the new run" }));
    expect(onRetry).not.toHaveBeenCalled();
  });

  it.each([
    ["organization", () => useOrgStore.setState({ activeOrgId: "org-b" })],
    [
      "account",
      () =>
        useAuthStore.setState({ user: { ...USER, id: "account-b" }, sessionOwnerId: "account-b" }),
    ],
    ["refusal", () => useOrgStore.setState({ refusedOrgIds: ["org-a"] })],
  ] as const)("closes a review when its %s changes", async (_label, change) => {
    const { onRetry } = mount();
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByRole("checkbox"));
    act(change);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onRetry).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("cannot carry consent to a different run", async () => {
    const { onRetry, rerender } = mount();
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByRole("checkbox"));
    rerender(<RunRetryButton runId="run-b" hasMedia busy={false} onRetry={onRetry} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(onRetry).not.toHaveBeenCalled();
  });
});
