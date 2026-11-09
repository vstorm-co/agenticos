import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { OnboardingPlaceholder } from "./onboarding-placeholder";
vi.mock("@/components/layout/auth-guard", () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/layout/active-org-guard", () => ({ ActiveOrgGuard: () => null }));
vi.mock("@/components/layout/account-locale", () => ({ AccountLocale: () => null }));
vi.mock("./start-entry", () => ({ StartEntry: () => <h1>First task</h1> }));
it("routes historical onboarding links into the working start hub", () => {
  render(<OnboardingPlaceholder />);
  expect(screen.getByRole("heading", { name: "First task" })).toBeVisible();
});
