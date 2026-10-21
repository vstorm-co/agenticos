import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { OnboardingTour } from "./onboarding-tour";
import { RestartTourButton } from "./restart-tour-button";
import { activateTab, pulse, waitForElement } from "@/components/onboarding/spotlight";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { visibleTourSteps } from "@/lib/onboarding/tour";
import { useAuthStore, useOnboardingStore } from "@/stores";
import { Perm, type Permission } from "@/types/permissions";
import type { DriveStep } from "driver.js";
import type { User } from "@/types";

const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
// One stable router across renders, so a test can assert where the tour sent the
// reader - a fresh `push` per `useRouter()` call would record nothing.
const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

const localeRouter = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => localeRouter,
  usePathname: () => "/dashboard",
}));

// The spotlight is the DOM/driver.js boundary; mocking it lets the test drive the
// orchestration - which step's copy shows, and that Next advances - without
// driver.js's real layout, which jsdom cannot provide. `waitForElement` resolves
// at once so a targeted step highlights immediately.
const spotlight = vi.hoisted(() => ({ highlight: vi.fn(), destroy: vi.fn() }));
vi.mock("@/components/onboarding/spotlight", () => ({
  createTourDriver: () => ({ highlight: spotlight.highlight, destroy: spotlight.destroy }),
  waitForElement: vi.fn(async () => ({}) as Element),
  activateTab: vi.fn(),
  pulse: vi.fn(async () => {}),
  isTypingTarget: vi.fn(() => false),
  revealDisclosures: vi.fn(),
  keepClearOf: vi.fn(),
  prefersReducedMotion: () => false,
}));
// The light the reader sees. `focus` records what it was pointed at and resolves
// at once, unless a test holds it to prove what waits for the light to land.
const light = vi.hoisted(() => ({
  focus: vi.fn(async (_element: Element | null) => {}),
  destroy: vi.fn(),
}));
const createTourSpotlight = vi.hoisted(() => vi.fn(() => light));
vi.mock("@/components/onboarding/tour-spotlight", () => ({ createTourSpotlight }));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

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
  // The engine resolves an example to open for each detail walk - an agent for
  // the builder, a collection for the KB, an organization for members/roles - so
  // `/agents`, `/kb` and `/orgs` have to answer with a list shape, not the
  // permission set every other GET returns.
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === "/agents") {
      return Promise.resolve({
        items: [{ id: "agent-1", slug: "agenticos", name: "AgenticOS" }],
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
  useOnboardingStore.setState({ isOpen: false, index: 0, mode: "tour", flowId: null, offer: null });
  useAuthStore.setState({ user: user(), isAuthenticated: true, isLoading: false });
});

describe("OnboardingTour", () => {
  it("auto-opens on the dashboard and welcomes a new user", async () => {
    servePermissions(OWNER);
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));
    expect(shownStep().popover?.progressText).toBe(`Step 1 of ${OWNER_LAUNCH}`);
  });

  it("offers the console's languages on the welcome card, and only there (#2072)", async () => {
    servePermissions(OWNER);
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));

    const description = document.createElement("div");
    shownStep().popover?.onPopoverRender?.({ description } as never, {} as never);
    const choices = Array.from(description.querySelectorAll("button"));
    expect(description.querySelector('[role="group"]')).toHaveAttribute("aria-label", "Language");
    expect(choices.find((b) => b.getAttribute("aria-pressed") === "true")?.textContent).toContain(
      "English",
    );
    choices.find((b) => b.textContent?.includes("English"))?.click();
    choices.find((b) => b.textContent?.includes("Polski"))?.click();
    expect(localeRouter.push).toHaveBeenCalledTimes(1);
    expect(localeRouter.push).toHaveBeenCalledWith("/dashboard", { locale: "pl" });

    act(() => shownStep().popover?.onNextClick?.(undefined, {} as DriveStep, {} as never));
    await waitFor(() => expect(shownStep().popover?.title).toBe("Slice the dashboard"));
    expect(shownStep().popover?.onPopoverRender).toBeUndefined();
  });

  it("asks the reader's role on the welcome card and keeps it on their account (#2301)", async () => {
    servePermissions(OWNER);
    vi.mocked(apiClient.patch).mockResolvedValue(user({ job_title: "Sales" }));
    useAuthStore.setState({ user: user({ job_title: "Finance" }) });
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));

    const description = document.createElement("div");
    shownStep().popover?.onPopoverRender?.({ description } as never, {} as never);
    const roles = description.querySelector(
      '[aria-label="What do you do? Your agents will know."]',
    );
    const buttons = Array.from(roles?.querySelectorAll("button") ?? []);
    expect(buttons.find((b) => b.getAttribute("aria-pressed") === "true")?.textContent).toBe(
      "Finance",
    );
    buttons.find((b) => b.textContent === "Sales")?.click();

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/users/me", { job_title: "Sales" }),
    );
    await waitFor(() => expect(useAuthStore.getState().user?.job_title).toBe("Sales"));
  });

  it("lets a role that could not be saved go quietly, for Settings to hold", async () => {
    servePermissions(OWNER);
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("offline"));
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));

    const description = document.createElement("div");
    shownStep().popover?.onPopoverRender?.({ description } as never, {} as never);
    const roles = description.querySelector(
      '[aria-label="What do you do? Your agents will know."]',
    );
    Array.from(roles?.querySelectorAll("button") ?? [])[0]?.click();

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("advances to the next highlight when Next is clicked", async () => {
    // The bug this replaces: a click on Next did nothing once a spotlight was up.
    servePermissions(OWNER);
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));

    act(() => shownStep().popover?.onNextClick?.(undefined, {} as DriveStep, {} as never));
    await waitFor(() => expect(shownStep().popover?.title).toBe("Slice the dashboard"));
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

  it("returns the reader to the dashboard when the first-run tour is closed", async () => {
    // The tour walks across the product and would otherwise leave a new user on
    // its last page; closing it should land them on the home they started from.
    servePermissions(OWNER);
    vi.mocked(apiClient.patch).mockResolvedValue(user({ onboarding_completed_at: "2026-02-02" }));
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));

    act(() => shownStep().popover?.onCloseClick?.(undefined, {} as DriveStep, {} as never));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith(ROUTES.DASHBOARD));
  });

  it("offers to build the first agent when the first-run tour is finished", async () => {
    // The headline of Phase 2: finishing onboarding asks whether to create the
    // first agent together. Declining is silent; the Agents "?" re-offers it.
    servePermissions(OWNER);
    useOnboardingStore.setState({ isOpen: true, index: 999, mode: "tour" });
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(spotlight.highlight).toHaveBeenCalled());

    act(() => shownStep().popover?.onNextClick?.(undefined, {} as DriveStep, {} as never));
    expect(useOnboardingStore.getState().offer).toBe("create-agent");
  });

  it("reminds the reader about the '?' when the first run ends, either way out", async () => {
    // The tour never returns (completion is server truth), so leaving it —
    // skipped or finished - is the one moment to say the "?" replays any page's
    // tips. A "?" replay itself gets no reminder: it was opened from the "?".
    servePermissions(OWNER);
    vi.mocked(apiClient.patch).mockResolvedValue(user({ onboarding_completed_at: "2026-02-02" }));
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));

    act(() => shownStep().popover?.onCloseClick?.(undefined, {} as DriveStep, {} as never));
    expect(toast.info).toHaveBeenCalledWith(
      "You can replay any page's tips whenever you like - just click the ? in its header.",
    );
  });

  it("offers the section's create flow when a '?' walk runs to its end", async () => {
    // Every section's "?" ends by asking whether to make the thing the section
    // is for - the re-entry into the interactive flows.
    servePermissions(OWNER);
    nav.pathname = "/skills";
    useOnboardingStore.setState({ isOpen: true, index: 99, mode: "page" });
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(spotlight.highlight).toHaveBeenCalled());

    act(() => shownStep().popover?.onNextClick?.(undefined, {} as DriveStep, {} as never));
    expect(useOnboardingStore.getState().offer).toBe("create-skill");
  });

  it("a '?' walk closed early makes no create offer", async () => {
    // Leaving is not finishing, so an early close asks nothing.
    servePermissions(OWNER);
    nav.pathname = "/skills";
    useOnboardingStore.setState({ isOpen: true, index: 0, mode: "page" });
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(spotlight.highlight).toHaveBeenCalled());

    act(() => shownStep().popover?.onCloseClick?.(undefined, {} as DriveStep, {} as never));
    expect(useOnboardingStore.getState().offer).toBeNull();
  });

  it("leaves a '?' replay where it was opened, not on the dashboard", async () => {
    // Page-mode help is about one page; closing it must not yank the reader away.
    servePermissions(OWNER);
    nav.pathname = "/agents";
    useOnboardingStore.setState({ isOpen: true, index: 0, mode: "page" });
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(spotlight.highlight).toHaveBeenCalled());

    act(() => shownStep().popover?.onCloseClick?.(undefined, {} as DriveStep, {} as never));
    expect(router.push).not.toHaveBeenCalledWith(ROUTES.DASHBOARD);
    // And no "?" reminder either - this walk was opened from the "?" itself.
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("asks for the detail lists only when the walk has somewhere to open", async () => {
    // Three list queries stand behind the detail stops. The vault section has no
    // detail view, so a "?" there used to fetch agents, collections and
    // organizations to answer a question none of its steps asks.
    servePermissions(OWNER);
    nav.pathname = ROUTES.VAULT;
    useOnboardingStore.setState({ isOpen: true, index: 0, mode: "page" });
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(spotlight.highlight).toHaveBeenCalled());

    const asked = vi.mocked(apiClient.get).mock.calls.map(([path]) => path);
    expect(asked).not.toContain("/agents");
    expect(asked).not.toContain("/kb");
    expect(asked).not.toContain("/orgs");
  });

  it("asks for them on a walk that does step into a detail view", async () => {
    // The Agents walk continues into the builder, which has no route of its own —
    // so the example to open has to be resolved from the list.
    servePermissions(OWNER);
    nav.pathname = ROUTES.AGENTS;
    useOnboardingStore.setState({ isOpen: true, index: 0, mode: "page" });
    render(<OnboardingTour />, { wrapper });

    await waitFor(() =>
      expect(vi.mocked(apiClient.get).mock.calls.map(([path]) => path)).toContain("/agents"),
    );
  });
});

describe("OnboardingTour's light", () => {
  // `clearAllMocks` keeps implementations, and these tests replace both.
  beforeEach(() => {
    light.focus.mockImplementation(async () => {});
    vi.mocked(waitForElement).mockImplementation(async () => ({}) as Element);
    createTourSpotlight.mockImplementation(() => light);
  });

  /** A Radix tab trigger as the tour finds it: a `data-tour` and its open state. */
  function tab(anchor: string, state: "active" | "inactive"): HTMLElement {
    const trigger = document.createElement("button");
    trigger.setAttribute("data-tour", anchor);
    trigger.setAttribute("data-state", state);
    return trigger;
  }

  /** Serve `waitForElement` from these elements by their anchor. */
  function serveElements(...elements: HTMLElement[]) {
    vi.mocked(waitForElement).mockImplementation(async (selector: string) => {
      return elements.find((element) => selector.includes(`"${element.dataset.tour}"`)) ?? null;
    });
  }

  function openBuilderHelp() {
    // The builder's "?" opens on its instructions stop, which names the Build tab.
    servePermissions(OWNER);
    nav.pathname = "/agents/agent-1";
    useOnboardingStore.setState({ isOpen: true, index: 0, mode: "page" });
  }

  it("goes straight to the target when its tab is already open", async () => {
    // The light used to climb to the tab bar, press a tab that was already
    // selected and drop back down on every consecutive stop in one tab.
    const target = document.createElement("div");
    target.dataset.tour = "agent-instructions-header";
    serveElements(tab("agent-tab-build", "active"), target);
    openBuilderHelp();
    render(<OnboardingTour />, { wrapper });

    await waitFor(() => expect(light.focus).toHaveBeenCalledWith(target));
    // The step re-runs as the builder's example agent resolves, so the target can
    // be asked for more than once — but the light never goes anywhere else.
    expect(light.focus.mock.calls.every(([element]) => element === target)).toBe(true);
    expect(pulse).not.toHaveBeenCalled();
    expect(activateTab).not.toHaveBeenCalled();
  });

  it("presses a closed tab only once the light has arrived on it", async () => {
    const trigger = tab("agent-tab-build", "inactive");
    const target = document.createElement("div");
    target.dataset.tour = "agent-instructions-header";
    serveElements(trigger, target);
    // Every travel to the tab is held — the step re-runs as the builder's example
    // agent resolves, and each run asks again — until the test lands them.
    let arrived = false;
    const waiting: (() => void)[] = [];
    const land = () => {
      arrived = true;
      waiting.forEach((resolve) => resolve());
    };
    light.focus.mockImplementation((element) =>
      element === trigger && !arrived
        ? new Promise<void>((resolve) => waiting.push(resolve))
        : Promise.resolve(),
    );
    openBuilderHelp();
    render(<OnboardingTour />, { wrapper });

    await waitFor(() => expect(light.focus).toHaveBeenCalledWith(trigger));
    // Still travelling: the press would play under a light that is not there yet.
    expect(pulse).not.toHaveBeenCalled();

    land();
    await waitFor(() => expect(activateTab).toHaveBeenCalledWith(trigger));
    expect(pulse).toHaveBeenCalledWith(trigger, expect.any(AbortSignal), expect.any(Number));
    await waitFor(() => expect(light.focus).toHaveBeenLastCalledWith(target));
  });

  it("presses the sidebar link that leads to another page, then goes there", async () => {
    // A page change shows what causes it: the light lands on the page's sidebar
    // link, the link is pressed, and only then does the page change.
    servePermissions(OWNER);
    const link = document.createElement("a");
    link.setAttribute("href", ROUTES.CHAT);
    vi.mocked(waitForElement).mockImplementation(async (selector: string) =>
      selector === `a[href$="${ROUTES.CHAT}"]` ? link : null,
    );
    const chat = visibleTourSteps(() => true).findIndex((step) => step.page === ROUTES.CHAT);
    useOnboardingStore.setState({ isOpen: true, index: chat, mode: "tour" });
    render(<OnboardingTour />, { wrapper });

    await waitFor(() => expect(router.push).toHaveBeenCalledWith(ROUTES.CHAT));
    expect(light.focus).toHaveBeenCalledWith(link);
    expect(pulse).toHaveBeenCalledWith(link, expect.any(AbortSignal), expect.any(Number));
    // Pressed before the page changed, not after.
    expect(vi.mocked(pulse).mock.invocationCallOrder[0]).toBeLessThan(
      router.push.mock.invocationCallOrder[0]!,
    );
  });

  it("lights nothing on a step that describes no control", async () => {
    servePermissions(OWNER);
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));
    expect(light.focus).toHaveBeenLastCalledWith(null);
  });

  it("takes the light down with the tour", async () => {
    servePermissions(OWNER);
    vi.mocked(apiClient.patch).mockResolvedValue(user({ onboarding_completed_at: "2026-02-02" }));
    render(<OnboardingTour />, { wrapper });
    await waitFor(() => expect(light.focus).toHaveBeenCalled());

    act(() => shownStep().popover?.onCloseClick?.(undefined, {} as DriveStep, {} as never));
    await waitFor(() => expect(light.destroy).toHaveBeenCalled());
  });

  it("draws with a live light after React re-runs its effects", async () => {
    // StrictMode in development, and Fast Refresh on an edit, tear the effects
    // down and run them again with the refs kept. A light destroyed by the first
    // pass and still held by the ref was reused: no dim, no ring, and a travel
    // that never resolved, so the walk stalled with Next greyed.
    const made: { focus: typeof light.focus; destroy: ReturnType<typeof vi.fn>; dead: boolean }[] =
      [];
    createTourSpotlight.mockImplementation(() => {
      const instance = {
        dead: false,
        focus: vi.fn(async (_element: Element | null) => {}),
        destroy: vi.fn(() => {
          instance.dead = true;
        }),
      };
      made.push(instance);
      return instance;
    });
    servePermissions(OWNER);
    useOnboardingStore.setState({ isOpen: true, index: 0, mode: "tour" });
    // The permissions already answered, so the walk is on a step at the very first
    // render — the case where the light exists before the effects are re-run.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(qk.organizations.permissions("current"), {
      organization_id: "org-1",
      role: "owner",
      is_app_admin: false,
      permissions: OWNER.map((permission) => ({ permission, scope: "all" })),
    });
    render(
      <StrictMode>
        <QueryClientProvider client={client}>
          <OnboardingTour />
        </QueryClientProvider>
      </StrictMode>,
    );

    await waitFor(() => expect(shownStep().popover?.title).toBe("Welcome to AgenticOS"));
    const lit = made.filter((instance) => instance.focus.mock.calls.length > 0).at(-1);
    expect(lit?.dead).toBe(false);
  });
});

describe("RestartTourButton", () => {
  it("opens the current page's tips in page mode", async () => {
    render(<RestartTourButton />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Show tips for this page" }));
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, index: 0, mode: "page" });
  });
});
