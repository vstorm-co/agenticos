import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingTour } from "./onboarding-tour";
import { RestartTourButton } from "./restart-tour-button";
import { apiClient } from "@/lib/api-client";
import { useAuthStore, useOnboardingStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { User } from "@/types";

const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** A Viewer holds the three view permissions and nothing else. */
const VIEWER = [Perm.agentsView, Perm.skillsView, Perm.collectionsView];
/** An Owner holds the lot; the tour shows every step. */
const OWNER = Object.values(Perm);

function user(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    email: "a@example.com",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    onboarding_completed_at: null,
    ...overrides,
  };
}

function servePermissions(permissions: readonly string[]) {
  vi.mocked(apiClient.get).mockResolvedValue({
    organization_id: "org-1",
    role: "member",
    is_app_admin: false,
    permissions: permissions.map((permission) => ({ permission, scope: "all" })),
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  nav.pathname = "/dashboard";
  useOnboardingStore.setState({ isOpen: false, index: 0 });
  useAuthStore.setState({ user: user(), isAuthenticated: true });
});

describe("OnboardingTour", () => {
  it("auto-opens on the dashboard and welcomes a new user", async () => {
    servePermissions(OWNER);
    render(<OnboardingTour />, { wrapper });
    expect(await screen.findByText("Welcome to AgenticOS")).toBeInTheDocument();
  });

  it("skips the steps a Viewer cannot act on", async () => {
    servePermissions(VIEWER);
    render(<OnboardingTour />, { wrapper });
    await screen.findByText("Welcome to AgenticOS");

    // Two of the nine steps are gated on permissions the Viewer lacks, so the
    // walkthrough it sees is seven long and never stops on either page.
    expect(screen.getByText("Step 1 of 7")).toBeInTheDocument();

    const user_ = userEvent.setup();
    for (let i = 0; i < 6; i++) {
      expect(screen.queryByText("Watch activity")).not.toBeInTheDocument();
      expect(screen.queryByText("The vault")).not.toBeInTheDocument();
      await user_.click(screen.getByRole("button", { name: "Next" }));
    }
    expect(await screen.findByText("You're all set")).toBeInTheDocument();
    expect(screen.getByText("Step 7 of 7")).toBeInTheDocument();
  });

  it("walks an Owner through the full nine steps, Activity and Vault included", async () => {
    servePermissions(OWNER);
    render(<OnboardingTour />, { wrapper });
    await screen.findByText("Welcome to AgenticOS");
    expect(screen.getByText("Step 1 of 9")).toBeInTheDocument();

    const user_ = userEvent.setup();
    const seen = new Set<string>();
    for (let i = 0; i < 8; i++) {
      if (screen.queryByText("Watch activity")) seen.add("activity");
      if (screen.queryByText("The vault")) seen.add("vault");
      await user_.click(screen.getByRole("button", { name: "Next" }));
    }
    if (screen.queryByText("The vault")) seen.add("vault");
    expect(seen).toEqual(new Set(["activity", "vault"]));
    expect(await screen.findByText("You're all set")).toBeInTheDocument();
  });

  it("persists completion when finished, so it does not return", async () => {
    servePermissions(VIEWER);
    vi.mocked(apiClient.patch).mockResolvedValue(
      user({ onboarding_completed_at: "2026-02-02T00:00:00Z" }),
    );
    render(<OnboardingTour />, { wrapper });
    await screen.findByText("Welcome to AgenticOS");

    const user_ = userEvent.setup();
    for (let i = 0; i < 6; i++) await user_.click(screen.getByRole("button", { name: "Next" }));
    await user_.click(screen.getByRole("button", { name: "Finish" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/users/me", {
        onboarding_completed_at: expect.any(String),
      }),
    );
    await waitFor(() => expect(screen.queryByText("You're all set")).not.toBeInTheDocument());
  });

  it("skipping from the first step also persists completion", async () => {
    servePermissions(VIEWER);
    vi.mocked(apiClient.patch).mockResolvedValue(user({ onboarding_completed_at: "x" }));
    render(<OnboardingTour />, { wrapper });
    await screen.findByText("Welcome to AgenticOS");

    await userEvent.setup().click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/users/me", expect.anything()),
    );
  });
});

describe("RestartTourButton", () => {
  it("reopens the walkthrough at the first step, from wherever it had reached", async () => {
    useOnboardingStore.setState({ isOpen: false, index: 4 });
    render(<RestartTourButton />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Replay the walkthrough" }));
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, index: 0 });
  });
});
