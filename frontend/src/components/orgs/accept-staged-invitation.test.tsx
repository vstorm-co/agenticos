import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AcceptStagedInvitation } from "./accept-staged-invitation";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const acceptStaged = vi.fn();
vi.mock("@/lib/invitation-staging", () => ({
  acceptStagedInvitation: () => acceptStaged(),
}));

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("closing a staged invitation after sign-in", () => {
  it("redeems the staged cookie and sends them to their organizations", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    acceptStaged.mockResolvedValue(undefined);

    render(<AcceptStagedInvitation />);
    screen.getByRole("button", { name: /accept/i }).click();

    await waitFor(() => expect(acceptStaged).toHaveBeenCalled());
    await screen.findByText(/joined/i);

    vi.advanceTimersByTime(2000);
    expect(push).toHaveBeenCalledWith("/orgs");
  });

  it("says a refused or expired invitation was refused", async () => {
    // A lapsed handle or a page opened without one comes back as a refusal from the
    // accept call, the same as any other.
    acceptStaged.mockRejectedValue(new Error("no pending invitation"));

    render(<AcceptStagedInvitation />);
    screen.getByRole("button", { name: /accept/i }).click();

    await screen.findByText(/failed/i);
  });
});
