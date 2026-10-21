import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PairDevice } from "./pair-device";

const env = vi.hoisted(() => ({
  code: "c0de" as string | null,
  redeem: vi.fn(),
  adopt: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(env.code ? { code: env.code } : {}),
}));
vi.mock("@/lib/pairing-api", () => ({ redeemPairingCode: env.redeem }));
vi.mock("@/hooks/use-auth", () => ({ useAdoptSession: () => env.adopt }));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ replace: env.replace }) }));

beforeEach(() => {
  env.code = "c0de";
  vi.clearAllMocks();
});

describe("PairDevice", () => {
  it("redeems the scanned code once, adopts the session and opens the console", async () => {
    env.redeem.mockResolvedValue({ user: { id: "u1" }, access_token: "acc" });
    const { rerender } = render(<PairDevice />);
    rerender(<PairDevice />);
    expect(screen.getByText("Signing you in")).toBeInTheDocument();
    await waitFor(() => expect(env.replace).toHaveBeenCalledWith("/dashboard"));
    expect(env.redeem).toHaveBeenCalledTimes(1);
    expect(env.adopt).toHaveBeenCalledWith({ id: "u1" }, "acc");
  });

  it("says a spent code no longer works, and so does a link with no code", async () => {
    env.redeem.mockRejectedValue(new Error("401"));
    const { unmount } = render(<PairDevice />);
    expect(
      await screen.findByRole("heading", { name: "This code no longer works" }),
    ).toBeInTheDocument();
    unmount();

    env.code = null;
    render(<PairDevice />);
    expect(screen.getByRole("heading", { name: "This code no longer works" })).toBeInTheDocument();
  });

  it("does nothing with an answer that arrives after it has gone", async () => {
    let resolve: (value: unknown) => void = () => {};
    let reject: (reason: unknown) => void = () => {};
    env.redeem
      .mockReturnValueOnce(new Promise((r) => (resolve = r)))
      .mockReturnValueOnce(new Promise((_, r) => (reject = r)));
    env.code = "late";
    render(<PairDevice />).unmount();
    resolve({ user: { id: "u1" }, access_token: "acc" });
    env.code = "late-fail";
    render(<PairDevice />).unmount();
    reject(new Error("401"));
    await new Promise((r) => setTimeout(r, 0));
    expect(env.adopt).not.toHaveBeenCalled();
  });
});
