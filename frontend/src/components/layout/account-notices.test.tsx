import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AccountNotices } from "./account-notices";

const env = vi.hoisted(() => ({
  path: "/chat",
  auth: { isAuthenticated: true, isLoading: false },
}));
vi.mock("next/navigation", () => ({ usePathname: () => env.path }));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (select: (state: typeof env.auth) => unknown) => select(env.auth),
}));
vi.mock("@/components/onboarding/start-offer", () => ({
  StartOffer: () => <aside>Start offer</aside>,
}));
vi.mock("@/components/orgs/received-invitations", () => ({
  ReceivedInvitations: () => <button>Invitations</button>,
}));
beforeEach(() => {
  env.path = "/chat";
  env.auth = { isAuthenticated: true, isLoading: false };
});
it("puts simultaneous invitations and setup in the same overlay outside page content", () => {
  const { container } = render(<AccountNotices />);
  const overlay = container.querySelector("[data-account-notices]");
  expect(screen.getByRole("button", { name: "Invitations" }).parentElement).toBe(overlay);
  expect(screen.getByText("Start offer").parentElement).toBe(overlay);
});
it.each(["loading", "signed out", "another page"])(
  "does not mount setup queries while %s",
  (condition) => {
    if (condition === "loading") env.auth.isLoading = true;
    if (condition === "signed out") env.auth.isAuthenticated = false;
    if (condition === "another page") env.path = "/dashboard";
    render(<AccountNotices />);
    expect(screen.queryByText("Start offer")).not.toBeInTheDocument();
  },
);
it("keeps setup available on a locale-prefixed chat route", () => {
  env.path = "/pl/chat";
  render(<AccountNotices />);
  expect(screen.getByText("Start offer")).toBeVisible();
});
