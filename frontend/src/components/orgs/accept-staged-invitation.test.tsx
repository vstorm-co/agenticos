import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AcceptStagedInvitation } from "./accept-staged-invitation";

const push = vi.fn();
const searchParams = { value: new URLSearchParams() };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => searchParams.value,
}));

const acceptStaged = vi.fn();
vi.mock("@/lib/invitation-staging", () => ({
  acceptStagedInvitation: (flow: string | null) => acceptStaged(flow),
}));

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  searchParams.value = new URLSearchParams();
});

describe("closing a staged invitation after sign-in", () => {
  it("redeems the cookie of the flow the landing names and sends them to their organizations", async () => {
    // Two invitations staged side by side hold two cookies; the landing's `flow` is
    // what says which of them this tab is closing.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    searchParams.value = new URLSearchParams({ flow: "0123456789abcdef0123456789abcdef" });
    acceptStaged.mockResolvedValue(undefined);

    render(<AcceptStagedInvitation />);
    screen.getByRole("button", { name: /accept/i }).click();

    await waitFor(() =>
      expect(acceptStaged).toHaveBeenCalledWith("0123456789abcdef0123456789abcdef"),
    );
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
