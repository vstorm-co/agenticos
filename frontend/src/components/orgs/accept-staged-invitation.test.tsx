import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as renderBare, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useOrgStore } from "@/stores/org-store";

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

/** The card refetches the organization list after an accept, so it needs a client. */
function render(ui: ReactElement) {
  return renderBare(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  useOrgStore.setState({ activeOrgId: null });
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
    acceptStaged.mockResolvedValue("org-acme");

    render(<AcceptStagedInvitation />);
    screen.getByRole("button", { name: /accept/i }).click();

    await waitFor(() =>
      expect(acceptStaged).toHaveBeenCalledWith("0123456789abcdef0123456789abcdef"),
    );
    await screen.findByText(/joined/i);
    expect(useOrgStore.getState().activeOrgId).toBe("org-acme");

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
