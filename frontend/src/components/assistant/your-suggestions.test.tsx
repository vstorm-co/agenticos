import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { YourSuggestions } from "./your-suggestions";

/**
 * The person's side of the nightly look (#2301): switching it off for
 * themselves, and seeing - and bringing back - what it proposed.
 */

const state = vi.hoisted(() => ({
  optedOut: false,
  signedIn: true,
  orgOn: true as boolean | undefined,
  saveOptOut: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks", () => ({
  useOrganizations: () => ({
    activeOrg: state.orgOn === undefined ? null : { proactive_enabled: state.orgOn },
  }),
}));
vi.mock("@/hooks/use-account-profile", () => ({ useSaveProactiveOptOut: () => state.saveOptOut }));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (store: { user: { proactive_opt_out: boolean } | null }) => unknown) =>
    pick({ user: state.signedIn ? { proactive_opt_out: state.optedOut } : null }),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

beforeEach(() => {
  state.optedOut = false;
  state.signedIn = true;
  state.orgOn = true;
  state.saveOptOut.mockReset().mockResolvedValue(undefined);
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("YourSuggestions", () => {
  it("blocks another preference change while its write is pending", async () => {
    let finish: (() => void) | undefined;
    state.saveOptOut.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(<YourSuggestions />);
    const toggle = screen.getByRole("switch");
    await userEvent.click(toggle);
    expect(toggle).toBeDisabled();
    await userEvent.click(toggle);
    expect(state.saveOptOut).toHaveBeenCalledTimes(1);
    await act(async () => finish?.());
    expect(toggle).toBeEnabled();
  });

  it("handles an account still loading without claiming an opt-out", () => {
    state.signedIn = false;
    render(<YourSuggestions />);
    expect(screen.getByRole("switch")).toBeChecked();
  });

  it("lets a person leave themselves out, and back in", async () => {
    render(<YourSuggestions />);
    const mine = screen.getByRole("switch", { name: "Nightly suggestions for me" });
    expect(mine).toBeChecked();

    await userEvent.click(mine);

    expect(state.saveOptOut).toHaveBeenCalledWith(true);
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Nightly suggestions are off for you"),
    );
  });

  it("lets one who opted out back in", async () => {
    state.optedOut = true;
    render(<YourSuggestions />);

    await userEvent.click(screen.getByRole("switch", { name: "Nightly suggestions for me" }));

    expect(state.saveOptOut).toHaveBeenCalledWith(false);
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Nightly suggestions are on for you"),
    );
  });

  it("says when the organization has none made at all", () => {
    state.orgOn = false;
    render(<YourSuggestions />);
    expect(screen.getByText(/organization has nightly suggestions off/)).toBeInTheDocument();
  });

  it("says nothing of the organization it knows nothing about", () => {
    state.orgOn = undefined;
    render(<YourSuggestions />);
    expect(screen.queryByText(/organization has nightly suggestions off/)).toBeNull();
  });

  it("reports a failed preference change and leaves history to Inbox", async () => {
    state.saveOptOut.mockRejectedValue(new Error("down"));
    render(<YourSuggestions />);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: "Nightly suggestions for me" }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(screen.getByRole("switch")).toBeChecked();
  });
});
