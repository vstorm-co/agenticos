import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Onboarding } from "@/lib/onboarding-api";
import { StartHub } from "./start-hub";
const env = vi.hoisted(() => ({
  push: vi.fn(),
  save: vi.fn(),
  refetch: vi.fn(),
  data: null as Onboarding | null,
  error: null as unknown,
  organizations: [{}] as object[],
  orgError: null as unknown,
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: env.push }) }));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({}),
  useOrganizationList: () => ({
    isSuccess: true,
    data: env.organizations,
    error: env.orgError,
    refetch: env.refetch,
  }),
}));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({
    data: env.data,
    error: env.error,
    isLoading: false,
    waitingForScope: false,
    refetch: env.refetch,
    save: { mutateAsync: env.save, isPending: false, error: null },
  }),
}));
vi.mock("./start-language", () => ({ StartLanguage: () => null }));
vi.mock("./start-model", () => ({ StartModel: () => <h2>Model preparation</h2> }));
vi.mock("./start-next-steps", () => ({ StartNextSteps: () => <h2>Next steps</h2> }));
beforeEach(() => {
  vi.clearAllMocks();
  env.save.mockResolvedValue({});
  env.error = null;
  env.orgError = null;
  env.organizations = [{}];
  env.data = {
    organization_id: "org",
    organization_name: "Acme",
    goal: null,
    dismissed: false,
    can_prepare: false,
    can_configure_model: false,
    support_email: "owner@example.com",
    agents: [],
    latest_conversation_id: null,
    latest_completed_at: null,
    has_result: false,
  };
});
it("offers a member a real contact and examples, without admin configuration", async () => {
  render(<StartHub />);
  expect(screen.getByRole("link", { name: "owner@example.com" })).toHaveAttribute(
    "href",
    "mailto:owner@example.com",
  );
  expect(screen.queryByRole("heading", { name: "Model preparation" })).not.toBeInTheDocument();
  const [example] = screen.getAllByRole("button", { name: "View example" });
  if (!example) throw new Error("Missing example action");
  await userEvent.click(example);
  await screen.findByText("Recorded example result");
  expect(env.save).toHaveBeenCalledWith({ goal: "meeting" });
  expect(env.push).not.toHaveBeenCalled();
});
it("saves the goal before handing the task to a runnable agent", async () => {
  if (!env.data) throw new Error("missing fixture");
  env.data.agents = [{ id: "agent", name: "Team assistant" }];
  render(<StartHub />);
  const [example] = screen.getAllByRole("button", { name: "Try this task" });
  if (!example) throw new Error("Missing example action");
  await userEvent.click(example);
  await waitFor(() =>
    expect(env.push).toHaveBeenCalledWith(
      expect.stringMatching(/^\/chat\?with=agent&new=.*&example=meeting$/),
    ),
  );
  expect(env.save).toHaveBeenCalledWith({ goal: "meeting" });
});
it("returns to a completed result and offers optional next steps", () => {
  if (!env.data) throw new Error("missing fixture");
  env.data.has_result = true;
  env.data.latest_conversation_id = "conversation";
  render(<StartHub />);
  expect(screen.getByRole("link", { name: "Continue your last completed chat" })).toHaveAttribute(
    "href",
    "/chat?id=conversation",
  );
  expect(screen.getByRole("heading", { name: "Next steps" })).toBeVisible();
});
it("does not mistake a failed read for an empty workspace", () => {
  env.error = new Error("offline");
  render(<StartHub />);
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "View example" })).not.toBeInTheDocument();
});
it("explains an account with no assigned organization", () => {
  env.organizations = [];
  render(<StartHub />);
  expect(screen.getByRole("heading", { name: "Choose your workspace" })).toBeVisible();
});

it("opens a recorded example while preferences are pending and returns keyboard focus", async () => {
  let finish: (() => void) | undefined;
  env.save.mockReturnValue(
    new Promise<void>((resolve) => {
      finish = resolve;
    }),
  );
  render(<StartHub />);
  const [button] = screen.getAllByRole("button", { name: "View example" });
  if (!button) throw new Error("Missing example action");
  expect(button).toHaveAccessibleDescription("Turn meeting notes into an action plan");
  await userEvent.click(button);
  expect(await screen.findByText("Recorded example result")).toBeVisible();
  expect(button).toHaveAttribute("aria-busy", "true");
  await userEvent.click(screen.getByRole("button", { name: "Back to getting started" }));
  expect(
    screen.getByRole("heading", { name: "Turn meeting notes into an action plan" }),
  ).toHaveFocus();
  await act(async () => {
    finish?.();
  });
  expect(button).toBeEnabled();
});
it("keeps the free demonstration available if saving the preference fails", async () => {
  env.save.mockRejectedValue(new Error("offline"));
  render(<StartHub />);
  const [button] = screen.getAllByRole("button", { name: "View example" });
  if (!button) throw new Error("Missing example action");
  await userEvent.click(button);
  expect(await screen.findByText("Recorded example result")).toBeVisible();
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Back to getting started" }));
  expect(button).toHaveFocus();
  expect(env.push).not.toHaveBeenCalled();
});

it("does not pull someone back into chat after they leave a pending start", async () => {
  if (!env.data) throw new Error("missing fixture");
  env.data.agents = [{ id: "agent", name: "Team assistant" }];
  let finish: (() => void) | undefined;
  env.save.mockReturnValue(
    new Promise<void>((resolve) => {
      finish = resolve;
    }),
  );
  const view = render(<StartHub />);
  const [button] = screen.getAllByRole("button", { name: "Try this task" });
  if (!button) throw new Error("Missing task action");
  await userEvent.click(button);
  expect(button).toHaveAttribute("aria-busy", "true");
  view.unmount();
  await act(async () => {
    finish?.();
  });
  expect(env.push).not.toHaveBeenCalled();
});

it("names the persisted task rather than implying every preview was saved", () => {
  if (!env.data) throw new Error("missing fixture");
  env.data.goal = "compare";
  render(<StartHub />);
  expect(
    screen.getByText(
      "Saved in this workspace: Compare three offers. You can continue on another device.",
    ),
  ).toBeVisible();
});
