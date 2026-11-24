import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import ViewerLayout from "./layout";

vi.mock("@/components/assistant/viewer-assistant-widget", () => ({
  ViewerAssistantWidget: () => <button type="button">App chat</button>,
}));
vi.mock("@/components/branding/deployment-gate", () => ({
  DeploymentGate: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/layout/active-org-guard", () => ({ ActiveOrgGuard: () => null }));
vi.mock("@/components/layout/auth-guard", () => ({
  AuthGuard: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/layout/impersonation-banner", () => ({ ImpersonationBanner: () => null }));
vi.mock("@/components/onboarding/onboarding-tour", () => ({ OnboardingTour: () => null }));

describe("the app viewer layout", () => {
  it("mounts the app chat launcher alongside the viewer", () => {
    render(
      <ViewerLayout>
        <div>App content</div>
      </ViewerLayout>,
    );

    expect(screen.getByText("App content")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "App chat" })).toBeInTheDocument();
  });
});
