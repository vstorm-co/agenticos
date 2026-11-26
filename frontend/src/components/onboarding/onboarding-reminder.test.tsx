import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useOnboardingLocationStore } from "@/stores/onboarding-location-store";
import { startLocationKey } from "@/lib/onboarding/start-location";
import { OnboardingResumeLink } from "./onboarding-resume-link";
import { OnboardingReminder } from "./onboarding-reminder";

const env = vi.hoisted(() => ({
  userId: "user",
  loadingUser: false,
  orgId: "org",
  policy: { enabled: true, snooze_days: 1 as 1 | 3 | 7 },
  startEnabled: vi.fn(),
  state: {
    isLoading: false,
    waitingForScope: false,
    error: null as unknown,
    data: { organization_id: "org", completed: false, dismissed: false },
    save: { isPending: false, isError: false, mutate: vi.fn() },
  },
}));
vi.mock("@/hooks/use-start", () => ({
  useStart: (enabled: boolean) => {
    env.startEnabled(enabled);
    return env.state;
  },
}));
vi.mock("@/components/settings/console-experience-provider", () => ({
  useOnboardingReminderPolicy: () => env.policy,
}));
vi.mock("@/stores", () => ({
  useAuthStore: <T,>(select: (value: { isLoading: boolean; user: { id: string } }) => T) =>
    select({ isLoading: env.loadingUser, user: { id: env.userId } }),
  useOrgStore: <T,>(select: (value: { activeOrgId: string }) => T) =>
    select({ activeOrgId: env.orgId }),
}));
beforeEach(() => {
  useOnboardingLocationStore.setState({ startLocations: {} });
  env.userId = "user";
  env.loadingUser = false;
  env.orgId = "org";
  env.policy = { enabled: true, snooze_days: 1 };
  env.startEnabled.mockClear();
  env.state.isLoading = false;
  env.state.waitingForScope = false;
  env.state.error = null;
  env.state.data = { organization_id: "org", completed: false, dismissed: false };
  env.state.save.isPending = false;
  env.state.save.isError = false;
  env.state.save.mutate.mockClear();
});
it("offers setup to an unfinished membership and asks the server to snooze it", async () => {
  render(<OnboardingReminder />);
  expect(screen.getByRole("link", { name: "Finish setup" })).toHaveAttribute("href", "/onboarding");
  await userEvent.click(screen.getByRole("button", { name: "Remind me tomorrow" }));
  expect(env.state.save.mutate).toHaveBeenCalledExactlyOnceWith({ dismissed: true });
  expect(screen.getByRole("region", { name: "Finish setup" })).toBeVisible();
});
it.each([false, true])(
  "hides the reminder during the server snooze, including collapsed=%s",
  (collapsed) => {
    env.state.data.dismissed = true;
    const view = render(<OnboardingReminder collapsed={collapsed} />);
    expect(screen.queryByRole("link", { name: "Finish setup" })).toBeNull();
    expect(screen.queryByRole("region")).toBeNull();
    env.state.data.dismissed = false;
    view.rerender(<OnboardingReminder />);
    expect(screen.getByRole("region", { name: "Finish setup" })).toBeVisible();
  },
);
it.each([
  "user loading",
  "query loading",
  "scope loading",
  "query error",
  "other org",
  "completed",
])("does not invent incomplete progress during %s", (condition) => {
  if (condition === "user loading") env.loadingUser = true;
  if (condition === "query loading") env.state.isLoading = true;
  if (condition === "scope loading") env.state.waitingForScope = true;
  if (condition === "query error") env.state.error = new Error("offline");
  if (condition === "other org") env.state.data.organization_id = "other";
  if (condition === "completed") env.state.data.completed = true;
  const { container } = render(<OnboardingReminder />);
  expect(container).toBeEmptyDOMElement();
});
it("retains the reminder and recovery action when the snooze write fails", () => {
  env.state.save.isError = true;
  render(<OnboardingReminder />);
  expect(screen.getByRole("alert")).toHaveTextContent("Could not hide the reminder");
  expect(screen.getByRole("button", { name: "Remind me tomorrow" })).toBeEnabled();
});
it("disables duplicate snooze writes while awaiting acceptance", () => {
  env.state.save.isPending = true;
  render(<OnboardingReminder />);
  expect(screen.getByRole("button", { name: "Remind me tomorrow" })).toBeDisabled();
});
it("keeps a named icon in the collapsed rail and closes a phone drawer on navigation", async () => {
  const onNavigate = vi.fn();
  render(<OnboardingReminder collapsed onNavigate={onNavigate} />);
  await userEvent.click(screen.getByRole("link", { name: "Finish setup" }));
  expect(onNavigate).toHaveBeenCalledOnce();
  expect(screen.queryByRole("region")).toBeNull();
});

it("resumes only this account and organization, then clears the hint on confirmed completion", () => {
  const navigation = useOnboardingLocationStore.getState();
  navigation.rememberStartLocation(
    "user",
    "org",
    "/onboarding?start-step=admin.deployment&workspace=org&question=announcement",
  );
  navigation.rememberStartLocation(
    "other-user",
    "org",
    "/onboarding?start-step=member.context&workspace=org",
  );
  const view = render(<OnboardingReminder />);
  expect(screen.getByRole("link", { name: "Finish setup" })).toHaveAttribute(
    "href",
    "/onboarding?start-step=admin.deployment&workspace=org&question=announcement",
  );
  env.userId = "third-user";
  view.rerender(<OnboardingReminder />);
  expect(screen.getByRole("link", { name: "Finish setup" })).toHaveAttribute("href", "/onboarding");
  env.userId = "user";
  env.orgId = "other-org";
  env.state.data = { organization_id: "other-org", completed: false, dismissed: false };
  view.rerender(<OnboardingReminder />);
  expect(screen.getByRole("link", { name: "Finish setup" })).toHaveAttribute("href", "/onboarding");
  env.orgId = "org";
  env.state.data = { organization_id: "org", completed: true, dismissed: false };
  view.rerender(<OnboardingReminder />);
  expect(
    useOnboardingLocationStore.getState().startLocations[startLocationKey("user", "org")],
  ).toBeUndefined();
  expect(
    useOnboardingLocationStore.getState().startLocations[startLocationKey("other-user", "org")],
  ).toBeDefined();
});
it("does not navigate to an invalid hint even if stale UI state contains one", () => {
  useOnboardingLocationStore.setState({
    startLocations: { [startLocationKey("user", "org")]: "https://example.com/private" },
  });
  render(<OnboardingReminder />);
  expect(screen.getByRole("link", { name: "Finish setup" })).toHaveAttribute("href", "/onboarding");
});

it("offers a distinct visible setup action below meaningful guidance", () => {
  render(<OnboardingReminder />);
  expect(screen.getByRole("heading", { name: "Make this workspace yours" })).toBeVisible();
  expect(
    screen.getByText("Add your details, choose how agents help, and try your first task."),
  ).toBeVisible();
  const link = screen.getByRole("link", { name: "Finish setup" });
  expect(link).toBeVisible();
  expect(link).not.toContainElement(screen.getByRole("heading"));
});

it("hides disabled or unresolved policy without requesting progress, retaining manual setup access", () => {
  env.policy.enabled = false;
  render(
    <>
      <OnboardingReminder />
      <OnboardingResumeLink />
    </>,
  );
  expect(screen.queryByRole("region", { name: "Finish setup" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Finish setup" })).toBeNull();
  expect(env.startEnabled).toHaveBeenLastCalledWith(false);
  expect(screen.getByRole("link", { name: "Open setup" })).toHaveAttribute("href", "/onboarding");
});
it.each([3, 7] as const)(
  "labels the server-owned %s-day snooze without adding local expiry state",
  async (days) => {
    env.policy.snooze_days = days;
    render(<OnboardingReminder />);
    await userEvent.click(screen.getByRole("button", { name: `Remind me in ${days} days` }));
    expect(env.state.save.mutate).toHaveBeenCalledExactlyOnceWith({ dismissed: true });
  },
);
it("manual setup resumes this account's sanitized location even when the reminder is off", () => {
  env.policy.enabled = false;
  useOnboardingLocationStore
    .getState()
    .rememberStartLocation(
      "user",
      "org",
      "/onboarding?start-step=admin.deployment&workspace=org&question=announcement",
    );
  render(<OnboardingResumeLink />);
  expect(screen.getByRole("link", { name: "Open setup" })).toHaveAttribute(
    "href",
    "/onboarding?start-step=admin.deployment&workspace=org&question=announcement",
  );
});

it("preserves the manual resume location when a server snooze hides the sidebar", () => {
  useOnboardingLocationStore
    .getState()
    .rememberStartLocation("user", "org", "/onboarding?start-step=member.context&workspace=org");
  env.state.data.dismissed = true;
  render(
    <>
      <OnboardingReminder />
      <OnboardingResumeLink />
    </>,
  );
  expect(screen.queryByRole("link", { name: "Finish setup" })).toBeNull();
  expect(screen.getByRole("link", { name: "Open setup" })).toHaveAttribute(
    "href",
    "/onboarding?start-step=member.context&workspace=org",
  );
});
