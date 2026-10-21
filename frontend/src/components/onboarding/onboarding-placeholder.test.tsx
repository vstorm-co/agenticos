import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OnboardingPlaceholder } from "./onboarding-placeholder";

vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "Northwind AI", logoUrl: null }),
}));
// The guard's own refusals are `auth-guard.test.tsx`'s; here somebody is signed in.
vi.mock("@/components/layout/auth-guard", () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => children,
}));

describe("the onboarding placeholder", () => {
  it("names the deployment and offers the way on", () => {
    render(<OnboardingPlaceholder />);

    expect(screen.getByText("Northwind AI")).toBeInTheDocument();
    expect(screen.getAllByRole("link").length).toBeGreaterThanOrEqual(2);
  });
});
