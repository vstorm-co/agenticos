import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Onboarding } from "@/lib/onboarding-api";
import { StartMember } from "./start-member";

const env = vi.hoisted(() => ({
  user: {
    id: "person",
    job_title: null as string | null,
    about: null,
    onboarding_completed_at: null as string | null,
  },
  callbacks: new Map<string, () => void>(),
  finish: vi.fn(),
  push: vi.fn(),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: env.push }) }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (select: (state: { user: typeof env.user }) => unknown) =>
    select({ user: env.user }),
}));
vi.mock("./start-guide", () => ({
  StartGuide: ({ message }: { message: string }) => <aside>{message}</aside>,
}));
vi.mock("./start-stage-artwork", () => ({ StartStageArtwork: () => null }));
vi.mock("./start-language", () => ({ StartLanguage: () => null }));
vi.mock("./start-companions", () => ({ StartCompanions: () => null }));
vi.mock("@/components/ui/avatar-face", () => ({ AvatarFace: () => null }));
vi.mock("./start-tasks", () => ({ StartTasks: () => <h2>First task examples</h2> }));
vi.mock("./start-finish", () => ({
  StartFinish: () => <button onClick={env.finish}>Finish setup</button>,
}));
vi.mock("@/components/settings/profile-identity-settings", () => ({
  ProfileIdentitySettings: ({
    section,
    onContinue,
    secondaryAction,
  }: {
    section: string;
    secondaryAction?: React.ReactNode;
    onContinue: () => void;
  }) => {
    env.callbacks.set(section, onContinue);
    return (
      <div>
        <button onClick={onContinue}>Save personal details</button>
        {secondaryAction}
      </div>
    );
  },
}));
const data: Onboarding = {
  organization_id: "workspace",
  organization_name: "Northwind",
  goal: null,
  dismissed: false,
  completed: false,
  snoozed_until: null,
  has_activity: false,
  has_result: false,
  agents: [],
  setup_agent: null,
  can_prepare: false,
  can_configure_model: false,
  support_email: null,
  latest_conversation_id: null,
  latest_completed_at: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  env.callbacks.clear();
  env.user.job_title = null;
  env.user.onboarding_completed_at = null;
  window.history.replaceState(null, "", "/onboarding?welcome=1&entry=account");
});
it("guides a new account through personal questions and a first task without administrator settings", async () => {
  render(<StartMember data={data} />);
  expect(screen.getByRole("heading", { name: "Welcome to Northwind" })).toBeVisible();
  expect(screen.getByText(/administrator handles/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Let's get started" }));
  expect(screen.getByRole("heading", { name: "Make yourself at home" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Save personal details" }));
  expect(
    screen.getByRole("heading", { name: "What should your agents know about you?" }),
  ).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Skip for now" }));
  expect(screen.getByRole("heading", { name: "First task examples" })).toBeVisible();
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Finish setup" }));
  expect(env.finish).toHaveBeenCalledOnce();
});
it("welcomes an existing account to another organization without repeating its profile", async () => {
  env.user.job_title = "Sales";
  render(<StartMember data={data} />);
  expect(screen.getByText(/profile already exists/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Use my saved profile" }));
  expect(screen.getByRole("heading", { name: "First task examples" })).toBeVisible();
  expect(env.callbacks.size).toBe(0);
});
it("lets the new member review saved details deliberately", async () => {
  env.user.job_title = "Sales";
  render(<StartMember data={data} />);
  await userEvent.click(screen.getByRole("button", { name: "Review my profile" }));
  expect(screen.getByRole("heading", { name: "Make yourself at home" })).toBeVisible();
});
it("restores the matching workspace's question after a reload", () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-step=member.context&workspace=workspace",
  );
  render(<StartMember data={data} />);
  expect(
    screen.getByRole("heading", { name: "What should your agents know about you?" }),
  ).toBeVisible();
});
it.each(["admin.deployment", "member.unknown"])(
  "does not restore an invalid or privileged member step: %s",
  (step) => {
    window.history.replaceState(null, "", `/onboarding?start-step=${step}&workspace=workspace`);
    render(<StartMember data={data} />);
    expect(screen.getByRole("heading", { name: "Welcome to Northwind" })).toBeVisible();
  },
);
it("never restores one organization's position into another", () => {
  window.history.replaceState(null, "", "/onboarding?start-step=member.context&workspace=another");
  render(<StartMember data={data} />);
  expect(screen.getByRole("heading", { name: "Welcome to Northwind" })).toBeVisible();
});
it("ignores a profile continuation after returning to the welcome", async () => {
  render(<StartMember data={data} />);
  await userEvent.click(screen.getByRole("button", { name: "Let's get started" }));
  const late = env.callbacks.get("identity");
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  act(() => late?.());
  expect(screen.getByRole("heading", { name: "Welcome to Northwind" })).toBeVisible();
});

it("lets an invited account reuse its saved identity even without a job description", async () => {
  window.history.replaceState(null, "", "/onboarding?welcome=1&entry=joined");
  render(<StartMember data={data} />);
  await userEvent.click(screen.getByRole("button", { name: "Use my saved profile" }));
  expect(screen.getByRole("heading", { name: "First task examples" })).toBeVisible();
  expect(env.callbacks.size).toBe(0);
});

it("keeps the requested full tour available from the member welcome", async () => {
  render(<StartMember data={data} />);
  await userEvent.click(screen.getByRole("button", { name: "Explore the application" }));
  expect(env.push).toHaveBeenCalledWith("/dashboard");
});
