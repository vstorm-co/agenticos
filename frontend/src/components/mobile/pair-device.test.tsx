import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PairDevice } from "./pair-device";

const env = vi.hoisted(() => ({
  code: "c0de" as string | null,
  preview: vi.fn(),
  redeem: vi.fn(),
  adopt: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(env.code ? { code: env.code } : {}),
}));
vi.mock("@/lib/pairing-api", () => ({
  previewPairingCode: env.preview,
  redeemPairingCode: env.redeem,
}));
vi.mock("@/hooks/use-auth", () => ({ useAdoptSession: () => env.adopt }));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ replace: env.replace }) }));
const user = { id: "u1", email: "owner@example.com", full_name: "Owner" };
beforeEach(() => {
  vi.resetAllMocks();
  env.code = "c0de";
  env.preview.mockResolvedValue(user);
  env.redeem.mockResolvedValue({ user, access_token: "acc" });
});

describe("PairDevice", () => {
  it("shows the target identity without replacing a session until explicit confirmation", async () => {
    render(<PairDevice />);
    expect(await screen.findByText(user.email)).toBeInTheDocument();
    expect(env.redeem).not.toHaveBeenCalled();
    expect(env.adopt).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm sign-in" }));
    await waitFor(() => expect(env.adopt).toHaveBeenCalledWith(user, "acc"));
    expect(env.replace).toHaveBeenCalledWith("/dashboard");
    expect(env.redeem).toHaveBeenCalledTimes(1);
  });
  it("cancels without spending the code or changing the session", async () => {
    render(<PairDevice />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(env.replace).toHaveBeenCalledWith("/login");
    expect(env.redeem).not.toHaveBeenCalled();
    expect(env.adopt).not.toHaveBeenCalled();
  });
  it("refuses missing, spent and expired codes", async () => {
    env.preview.mockRejectedValueOnce(new Error("expired"));
    const { unmount } = render(<PairDevice />);
    expect(
      await screen.findByRole("heading", { name: "This code no longer works" }),
    ).toBeInTheDocument();
    unmount();
    env.code = null;
    render(<PairDevice />);
    expect(screen.getByRole("heading", { name: "This code no longer works" })).toBeInTheDocument();
    expect(env.redeem).not.toHaveBeenCalled();
  });
  it("handles expiry between preview and confirmation without adopting an account", async () => {
    env.redeem.mockRejectedValueOnce(new Error("expired"));
    render(<PairDevice />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm sign-in" }));
    expect(
      await screen.findByRole("heading", { name: "This code no longer works" }),
    ).toBeInTheDocument();
    expect(env.adopt).not.toHaveBeenCalled();
  });
  it("ignores a preview that arrives after navigating to a different scanned code", async () => {
    let resolve: (value: typeof user) => void = () => {};
    env.preview.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const { rerender } = render(<PairDevice />);
    env.code = "second";
    rerender(<PairDevice />);
    await screen.findByText(user.email);
    await act(async () => resolve({ ...user, email: "attacker@example.com" }));
    expect(screen.queryByText("attacker@example.com")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm sign-in" }));
    expect(env.redeem).toHaveBeenCalledWith("second");
  });
});
