import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingTour } from "./onboarding-tour";
import { RestartTourButton } from "./restart-tour-button";
import { apiClient } from "@/lib/api-client";
import { visibleTourSteps } from "@/lib/onboarding/tour";
import { useAuthStore, useOnboardingStore } from "@/stores";
import { Perm, type Permission } from "@/types/permissions";
import type { DriveStep } from "driver.js";
import type { User } from "@/types";

const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

// The spotlight is the DOM/driver.js boundary; mocking it lets the test drive the
// orchestration — which step's copy shows, and that Next advances — without
// driver.js's real layout, which jsdom cannot provide. `waitForElement` resolves
// at once so a targeted step highlights immediately.
const spotlight = vi.hoisted(() => ({ highlight: vi.fn(), destroy: vi.fn() }));
vi.mock("@/components/onboarding/spotlight", () => ({
  createTourDriver: () => ({ highlight: spotlight.highlight, destroy: spotlight.destroy }),
  waitForElement: vi.fn(async () => ({}) as Element),
  activateTab: vi.fn(),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const VIEWER = [Perm.agentsView, Perm.skillsView, Perm.collectionsView];
const OWNER = Object.values(Perm);

// The walkthrough lengths are derived, not hard-coded, so adding a stop moves
// the progress text with the registry rather than reddening this file.
const OWNER_LAUNCH = visibleTourSteps(() => true).length;
const VIEWER_HELD = new Set<Permission>(VIEWER);
const VIEWER_LAUNCH = visibleTourSteps((permission) => VIEWER_HELD.has(permission)).length;

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
  // The engine resolves an example to open for each detail walk — an agent for
  // the builder, a collection for the KB, an organization for members/roles — so
  // `/agents`, `/kb` and `/orgs` have to answer with a list shape, not the
  // permission set every other GET returns.
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === "/agents") {
      return Promise.resolve({
        items: [{ id: "agent-1", slug: "getting-started", name: "Getting Started" }],
        total: 1,
      });
    }
    if (path === "/kb") {
      return Promise.resolve({
        items: [{ id: "kb-1", is_default: true, name: "Default collection" }],
        total: 1,
      });
    }
    if (path === "/orgs") {
      return Promise.resolve({
        items: [{ id: "org-1", is_personal: true, name: "Personal" }],
        total: 1,
      });
    }
    return Promise.resolve({
      organization_id: "org-1",
      role: "member",
      is_app_admin: false,
      permissions: permissions.map((permission) => ({ permission, scope: "all" })),
    });
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The most recent step driver was asked to highlight. */
function shownStep(): DriveStep {
  const call = spotlight.highlight.mock.calls.at(-1);
  if (!call) throw new Error("driver.highlight was never called");
  return call[0] as DriveStep;
}

beforeEach(() => {
  vi.clearAllMocks();
  nav.pathname = "/dashboard";
  useOnboardingStore.setState({ isOpen: false, index: 0, mode: "tour" });
  useAuthStore.setState({ user: user(), isAuthenticated: true });
});

describe("OnboardingTour", () => {
  it("auto-opens on the dashboard and welcomes a new user", async () => {
    servePermissions(OWNER);
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));
    expect(shownStep().popover?.progressText).toBe(`Step 1 of ${OWNER_LAUNCH}`);
  });

  it("advances to the next highlight when Next is clicked", async () => {
    // The bug this replaces: a click on Next did nothing once a spotlight was up.
    servePermissions(OWNER);
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));

    act(() => shownStep().popover?.onNextClick?.(undefined, {} as DriveStep, {} as never));
    await waitFor(() => expect(shownStep().popover?.title).toBe("Start here"));
    expect(shownStep().popover?.progressText).toBe(`Step 2 of ${OWNER_LAUNCH}`);
  });

  it("shows a view-only member their shorter tour", async () => {
    servePermissions(VIEWER);
    render(<OnboardingTour />, { wrapper });
    await waitFor(() =>
      expect(shownStep().popover?.progressText).toBe(`Step 1 of ${VIEWER_LAUNCH}`),
    );
  });

  it("persists completion when the tour is closed", async () => {
    servePermissions(OWNER);
    vi.mocked(apiClient.patch).mockResolvedValue(user({ onboarding_completed_at: "2026-02-02" }));
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));

    act(() => shownStep().popover?.onCloseClick?.(undefined, {} as DriveStep, {} as never));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/users/me", {
        onboarding_completed_at: expect.any(String),
      }),
    );
  });
});

describe("RestartTourButton", () => {
  it("opens the current page's tips in page mode", async () => {
    render(<RestartTourButton />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Show tips for this page" }));
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, index: 0, mode: "page" });
  });
});
