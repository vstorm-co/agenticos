import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { useOnboardingLocationStore } from "@/stores/onboarding-location-store";
import { startLocationKey } from "@/lib/onboarding/start-location";
import { StartEntry } from "./start-entry";
const env = vi.hoisted(() => ({
  completed: false,
  automatic: true,
  entry: "",
  flow: "",
  preferencesDone: false,
  resume: false,
  activity: false,
  ready: false,
  dismissed: false,
  pending: false,
  orgPending: false,
  noOrg: false,
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () =>
    new URLSearchParams(
      `${env.automatic ? "welcome=1" : ""}&entry=${env.entry}${env.resume ? "&start-step=member.context&workspace=org" : ""}${env.flow ? `&flow=${env.flow}` : ""}${env.preferencesDone ? "&preferences=done" : ""}`,
    ),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ replace: env.replace }) }));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({
    data: env.noOrg
      ? undefined
      : {
          organization_id: "org",
          completed: env.completed,
          dismissed: env.dismissed,
          has_result: false,
          has_activity: env.activity,
          agents: env.ready ? [{ id: "agent" }] : [],
        },
    isLoading: env.pending,
    waitingForScope: env.noOrg,
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizationList: () => ({ isPending: env.orgPending, data: env.noOrg ? [] : [{}] }),
}));
vi.mock("./start-hub", () => ({ StartHub: () => <h1>Workspace setup</h1> }));
vi.mock("./start-preferences", () => ({
  StartPreferences: ({
    onContinue,
    children,
  }: {
    onContinue: () => void;
    children?: ReactNode;
  }) => (
    <>
      {children}
      <h1>Personal preferences</h1>
      <button onClick={onContinue}>Finish preferences</button>
    </>
  ),
}));
vi.mock("@/components/orgs/accept-staged-invitation", () => ({
  AcceptStagedInvitation: ({ presentation }: { presentation: string }) => (
    <aside>Staged invitation {presentation}</aside>
  ),
}));
vi.mock("@/components/orgs/received-invitations", () => ({
  ReceivedInvitations: ({ presentation }: { presentation: string }) => (
    <aside>Received invitations {presentation}</aside>
  ),
}));
beforeEach(() => {
  useAuthStore.setState({ user: null });
  useOnboardingLocationStore.setState({ startLocations: {} });
  window.history.replaceState({}, "", "/onboarding");
  env.completed = false;
  Object.assign(env, {
    automatic: true,
    entry: "",
    flow: "",
    preferencesDone: false,
    resume: false,
    activity: false,
    ready: false,
    dismissed: false,
    pending: false,
    orgPending: false,
    noOrg: false,
  });
  env.replace.mockReset();
});
it.each(["activity", "ready", "dismissed"] as const)(
  "takes an automatic welcome to chat for %s",
  async (reason) => {
    env[reason] = true;
    render(<StartEntry />);
    await waitFor(() => expect(env.replace).toHaveBeenCalledWith("/chat"));
    expect(screen.queryByRole("heading", { name: "Workspace setup" })).not.toBeInTheDocument();
  },
);
it("keeps manually opened setup available to existing users", () => {
  env.automatic = false;
  env.activity = true;
  render(<StartEntry />);
  expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
  expect(env.replace).not.toHaveBeenCalled();
});
it("waits for the check before deciding", () => {
  env.pending = true;
  render(<StartEntry />);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  expect(env.replace).not.toHaveBeenCalled();
});
it("allows an administrator without any organization to create one", () => {
  env.noOrg = true;
  render(<StartEntry />);
  expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
});

it.each(["account", "joined"])(
  "starts fresh %s entry with preferences, then workspace setup",
  (entry) => {
    env.entry = entry;
    env.ready = true;
    render(<StartEntry />);
    expect(screen.getByRole("heading", { name: "Personal preferences" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Finish preferences" }));
    expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
    expect(env.replace).not.toHaveBeenCalled();
  },
);
it("keeps new-account onboarding before workspace activity checks", () => {
  env.entry = "account";
  env.ready = true;
  env.activity = true;
  render(<StartEntry />);
  expect(screen.getByRole("heading", { name: "Personal preferences" })).toBeVisible();
  expect(env.replace).not.toHaveBeenCalled();
});
it("embeds only the staged invitation during fresh preferences and preserves flow and navigation state on Continue", () => {
  env.entry = "account";
  env.flow = "0123456789abcdef0123456789abcdef";
  window.history.replaceState(
    { retained: "navigation-state" },
    "",
    `/onboarding?welcome=1&entry=account&flow=${env.flow}#anchor`,
  );
  render(<StartEntry />);
  expect(screen.getByText("Staged invitation inline")).toBeVisible();
  expect(screen.queryByText("Received invitations inline")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Finish preferences" }));
  expect(window.history.state).toEqual({ retained: "navigation-state" });
  expect(new URLSearchParams(window.location.search).get("preferences")).toBe("done");
  expect(new URLSearchParams(window.location.search).get("flow")).toBe(env.flow);
  expect(window.location.hash).toBe("#anchor");
  expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
  expect(screen.queryByText("Staged invitation inline")).not.toBeInTheDocument();
});

it("offers received invitations inline during preferences when no staged flow exists", () => {
  env.entry = "account";
  render(<StartEntry />);
  expect(screen.getByText("Received invitations inline")).toBeVisible();
  expect(screen.queryByText("Staged invitation inline")).not.toBeInTheDocument();
});

it.each(["account", "joined"])(
  "does not restart completed preferences after a %s refresh",
  (entry) => {
    env.entry = entry;
    env.preferencesDone = true;
    env.flow = "0123456789abcdef0123456789abcdef";
    render(<StartEntry />);
    expect(screen.queryByRole("heading", { name: "Personal preferences" })).not.toBeInTheDocument();
    expect(screen.queryByText("Staged invitation inline")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
  },
);

it("resumes a fresh-entry step without replaying preferences or placing invitations above the full-height hub", () => {
  env.entry = "account";
  env.resume = true;
  env.flow = "0123456789abcdef0123456789abcdef";
  render(<StartEntry />);
  expect(screen.queryByRole("heading", { name: "Personal preferences" })).not.toBeInTheDocument();
  expect(screen.queryByText("Staged invitation inline")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
});
it("keeps an explicitly resumed walkthrough open", () => {
  env.resume = true;
  env.ready = true;
  render(<StartEntry />);
  expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
});

it("keeps a resumed step's layout while data loads without exposing form controls", () => {
  env.pending = true;
  env.resume = true;
  render(<StartEntry />);
  expect(screen.getByRole("status")).toHaveAttribute("data-onboarding-skeleton", "context");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it.each(["pending", "orgPending"] as const)(
  "preserves the resumed layout on a direct link while %s",
  (pending) => {
    env.automatic = false;
    env.resume = true;
    env[pending] = true;
    render(<StartEntry />);
    expect(screen.getByRole("status")).toHaveAttribute("data-onboarding-skeleton", "context");
    expect(screen.queryByRole("heading", { name: "Workspace setup" })).not.toBeInTheDocument();
  },
);

it("remembers a safe current step without entry metadata and clears it after completion", async () => {
  env.automatic = false;
  env.entry = "joined";
  env.resume = true;
  useAuthStore.setState({
    user: {
      id: "user",
      email: "user@example.com",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
    },
  });
  const view = render(<StartEntry />);
  await waitFor(() =>
    expect(
      useOnboardingLocationStore.getState().startLocations[startLocationKey("user", "org")],
    ).toBe("/onboarding?start-step=member.context&workspace=org"),
  );
  env.completed = true;
  view.rerender(<StartEntry />);
  await waitFor(() =>
    expect(
      useOnboardingLocationStore.getState().startLocations[startLocationKey("user", "org")],
    ).toBeUndefined(),
  );
});

it.each(["admin.subscriptions", "member.subscriptions"])(
  "restores the subscription loading view: %s",
  async (step) => {
    const { startLoadingView } = await import("./start-skeleton");
    expect(startLoadingView(step, null)).toBe("subscriptions");
  },
);
