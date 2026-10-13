import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AcceptInvitation } from "./accept-invitation";
import { registerHref } from "@/lib/invitation-links";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}));

const auth = { isAuthenticated: true };
const acceptInvitation = vi.fn();
vi.mock("@/hooks", () => ({
  useAuth: () => auth,
  useInvitations: () => ({ acceptInvitation }),
}));

const TOKEN = "z6OPn2FNnpdtiNBBLB1Cn7WUgaGXGsYcdfrPADykQLg";

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  auth.isAuthenticated = true;
  acceptInvitation.mockReset();
});

describe("somebody who is not signed in", () => {
  it("is navigated nowhere, so the guard's own redirect survives", async () => {
    // The whole bug in one assertion. This used to push `/login?redirect=…`, a
    // parameter name nothing reads, over the `?returnTo=` AuthGuard had just
    // written - and the invitation was gone by the time they reached a sign-up
    // form (#1495).
    auth.isAuthenticated = false;

    render(<AcceptInvitation token={TOKEN} />);

    expect(push).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("is left on a login URL whose landing carries no token (#1414)", () => {
    // AuthGuard exchanges the token for an httpOnly handle and returns the invitee
    // to the credential-free `/invitations/pending`; the register link carries only
    // that landing on, never the token.
    const search = new URL("/login?returnTo=%2Finvitations%2Fpending", "https://example.test")
      .search;

    const href = registerHref(search);

    expect(href).toContain("returnTo=");
    expect(href).not.toContain(TOKEN);
  });
});

describe("somebody who is signed in", () => {
  it("accepts the token it was given and sends them to their organizations", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    acceptInvitation.mockResolvedValue(undefined);

    render(<AcceptInvitation token={TOKEN} />);
    screen.getByRole("button", { name: /accept/i }).click();

    await waitFor(() => expect(acceptInvitation).toHaveBeenCalledWith(TOKEN));
    await screen.findByText(/joined/i);

    vi.advanceTimersByTime(2000);
    expect(push).toHaveBeenCalledWith("/orgs");
  });

  it("says a refused invitation was refused, and offers a way off the page", async () => {
    acceptInvitation.mockRejectedValue(new Error("This invitation has expired"));

    render(<AcceptInvitation token={TOKEN} />);
    screen.getByRole("button", { name: /accept/i }).click();

    await screen.findByText(/failed/i);
    screen.getByRole("button", { name: /dashboard/i }).click();
    expect(push).toHaveBeenCalledWith("/dashboard");
  });

  it("disables the button while the accept is out, so one click is one accept", async () => {
    let settle: () => void = () => {};
    acceptInvitation.mockReturnValue(new Promise<void>((resolve) => (settle = resolve)));

    render(<AcceptInvitation token={TOKEN} />);
    screen.getByRole("button", { name: /accept/i }).click();

    const joining = await screen.findByRole("button", { name: /joining/i });
    expect(joining).toBeDisabled();

    settle();
    await waitFor(() => expect(acceptInvitation).toHaveBeenCalledTimes(1));
  });
});
