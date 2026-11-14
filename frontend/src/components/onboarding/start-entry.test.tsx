import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { StartEntry } from "./start-entry";
const env = vi.hoisted(() => ({
  automatic: true,
  entry: "",
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
      `${env.automatic ? "welcome=1" : ""}&entry=${env.entry}${env.resume ? "&start-step=member.context" : ""}`,
    ),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ replace: env.replace }) }));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({
    data: env.noOrg
      ? undefined
      : {
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
beforeEach(() => {
  Object.assign(env, {
    automatic: true,
    entry: "",
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
  "welcomes a fresh %s entry even when the organization has ready agents",
  (entry) => {
    env.entry = entry;
    env.ready = true;
    render(<StartEntry />);
    expect(screen.getByRole("heading", { name: "Workspace setup" })).toBeVisible();
    expect(env.replace).not.toHaveBeenCalled();
  },
);
it.each(["account", "joined"])(
  "does not restart the %s journey after personal activity",
  async (entry) => {
    env.entry = entry;
    env.ready = true;
    env.activity = true;
    render(<StartEntry />);
    await waitFor(() => expect(env.replace).toHaveBeenCalledWith("/chat"));
  },
);
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
