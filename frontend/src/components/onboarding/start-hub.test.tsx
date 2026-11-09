import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Onboarding } from "@/lib/onboarding-api";
import { StartHub } from "./start-hub";
const env = vi.hoisted(() => ({
  appAdmin: false,
  orgAdmin: false,
  push: vi.fn(),
  save: vi.fn(),
  finish: vi.fn(),
  refetch: vi.fn(),
  data: null as Onboarding | null,
  error: null as unknown,
  organizations: [{}] as object[],
  orgError: null as unknown,
  saveError: null as unknown,
}));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (pick: (state: { user: { is_app_admin: boolean } }) => unknown) =>
    pick({ user: { is_app_admin: env.appAdmin } }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => env.orgAdmin, isLoaded: true, error: null }),
}));
vi.mock("./start-administration", () => ({
  StartAdministration: ({ appAdmin }: { appAdmin: boolean }) => (
    <h1>{appAdmin ? "Application setup" : "Organization setup"}</h1>
  ),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: env.push }) }));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({ activeOrg: env.orgAdmin ? { id: "org", is_personal: false } : null }),
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
    save: { mutate: env.finish, mutateAsync: env.save, isPending: false, error: env.saveError },
  }),
}));
vi.mock("./start-language", () => ({ StartLanguage: () => null }));
vi.mock("./start-model", () => ({
  StartModel: ({ allowAdd, onPrepared }: { allowAdd: boolean; onPrepared: () => void }) => (
    <div>
      <p>{allowAdd ? "Can add a model" : "Existing models only"}</p>
      <button onClick={onPrepared}>Finish preparation</button>
    </div>
  ),
}));
vi.mock("./start-next-steps", () => ({ StartNextSteps: () => <h2>Next steps</h2> }));
beforeEach(() => {
  vi.clearAllMocks();
  env.appAdmin = false;
  env.orgAdmin = false;
  env.save.mockResolvedValue({});
  env.error = null;
  env.saveError = null;
  env.orgError = null;
  env.organizations = [{}];
  env.data = {
    organization_id: "org",
    organization_name: "Acme",
    goal: null,
    dismissed: false,
    completed: true,
    snoozed_until: null,
    setup_agent: null,
    can_prepare: false,
    can_configure_model: false,
    support_email: "owner@example.com",
    agents: [],
    latest_conversation_id: null,
    latest_completed_at: null,
    has_result: false,
    has_activity: false,
  };
});
it("starts inside a useful demonstration, with setup out of the way", () => {
  render(<StartHub />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "What could an agent help you with?",
  );
  expect(
    screen.getByRole("table", { name: "An action plan with the gaps made clear" }),
  ).toBeVisible();
  expect(screen.getByRole("note")).toHaveTextContent("No AI call");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText("Can add a model")).not.toBeInTheDocument();
  expect(env.save).not.toHaveBeenCalled();
  expect(env.push).not.toHaveBeenCalled();
});
it("switches between actual sample outputs and their source material", async () => {
  render(<StartHub />);
  await userEvent.click(screen.getByRole("radio", { name: /Compare options/ }));
  expect(screen.getByRole("table", { name: "Three offers, one that fits" })).toBeVisible();
  expect(screen.getByRole("radio", { name: /Compare options/ })).toBeChecked();
  expect(env.save).toHaveBeenCalledWith({ goal: "compare" });
  expect(env.push).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("tab", { name: "What the agent receives" }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("A: €80/month");
  await userEvent.click(screen.getByRole("radio", { name: /Find an answer/ }));
  expect(screen.getByRole("tab", { name: "Example answer" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Get approval before booking");
});
it.each(["close", "escape"])(
  "lets a member leave the access dialog with %s and returns focus",
  async (method) => {
    render(<StartHub />);
    const action = screen.getByRole("button", { name: "Get access to an agent" });
    await userEvent.click(action);
    const dialog = screen.getByRole("dialog", {
      name: "Your workspace needs a little preparation",
    });
    expect(within(dialog).getByRole("link", { name: "owner@example.com" })).toHaveAttribute(
      "href",
      "mailto:owner@example.com",
    );
    expect(within(dialog).getByRole("button", { name: "Check again" })).toBeVisible();
    expect(screen.queryByText("Can add a model")).not.toBeInTheDocument();
    if (method === "escape") await userEvent.keyboard("{Escape}");
    else await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(action).toHaveFocus());
  },
);
it.each([true, false])(
  "opens model setup only when requested, respecting add permission %s",
  async (allowAdd) => {
    if (!env.data) throw new Error("missing fixture");
    env.data.can_prepare = true;
    env.data.can_configure_model = allowAdd;
    render(<StartHub />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Set up my agent" }));
    const dialog = screen.getByRole("dialog", { name: "Connect AI and prepare your first task" });
    expect(
      within(dialog).getByText(allowAdd ? "Can add a model" : "Existing models only"),
    ).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Finish preparation" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  },
);
it("uses the saved choice on return", () => {
  if (!env.data) throw new Error("missing fixture");
  env.data.goal = "compare";
  render(<StartHub />);
  expect(screen.getByRole("radio", { name: /Compare options/ })).toBeChecked();
  expect(screen.getByRole("status")).toHaveTextContent("Choice saved to this workspace");
});
it("keeps demonstrations and access help available during a pending choice save", async () => {
  let finish: (() => void) | undefined;
  env.save.mockReturnValue(
    new Promise<void>((resolve) => {
      finish = resolve;
    }),
  );
  render(<StartHub />);
  await userEvent.click(screen.getByRole("radio", { name: /Compare options/ }));
  expect(screen.getByRole("table", { name: "Three offers, one that fits" })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Saving your choice");
  await userEvent.click(screen.getByRole("button", { name: "Get access to an agent" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  await userEvent.keyboard("{Escape}");
  await act(async () => {
    finish?.();
  });
});
it("keeps the chosen demonstration if preferences fail", async () => {
  env.save.mockRejectedValue(new Error("offline"));
  const view = render(<StartHub />);
  await userEvent.click(screen.getByRole("radio", { name: /Compare options/ }));
  env.saveError = new Error("offline");
  view.rerender(<StartHub />);
  expect(screen.getByRole("table", { name: "Three offers, one that fits" })).toBeVisible();
  expect(
    within(screen.getByRole("region", { name: "Compare three offers" })).getByRole("alert"),
  ).toHaveTextContent("Your choice wasn't saved");
  expect(screen.queryByText("Choice saved to this workspace")).not.toBeInTheDocument();
});
it("hands only an explicitly requested task to the selected runnable agent", async () => {
  if (!env.data) throw new Error("missing fixture");
  env.data.agents = [
    { id: "first", name: "First assistant" },
    { id: "second", name: "Second assistant" },
  ];
  render(<StartHub />);
  expect(env.push).not.toHaveBeenCalled();
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Who answers" }), "second");
  await userEvent.click(screen.getByRole("button", { name: "Try this task" }));
  await waitFor(() =>
    expect(env.push).toHaveBeenCalledWith(
      expect.stringMatching(/^\/chat\?with=second&new=.*&example=meeting$/),
    ),
  );
  expect(env.save).toHaveBeenCalledWith({ goal: "meeting" });
});
it("does not navigate after leaving a pending task launch", async () => {
  if (!env.data) throw new Error("missing fixture");
  env.data.agents = [{ id: "agent", name: "Team assistant" }];
  let finish: (() => void) | undefined;
  env.save.mockReturnValue(
    new Promise<void>((resolve) => {
      finish = resolve;
    }),
  );
  const view = render(<StartHub />);
  await userEvent.click(screen.getByRole("button", { name: "Try this task" }));
  expect(screen.getByRole("button", { name: "Try this task" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  view.unmount();
  await act(async () => {
    finish?.();
  });
  expect(env.push).not.toHaveBeenCalled();
});
it("returns to the latest result and permission-filtered next steps", () => {
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
it("does not present a failed read as an empty workspace", () => {
  env.error = new Error("offline");
  render(<StartHub />);
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
it("explains an account with no assigned organization", () => {
  env.organizations = [];
  render(<StartHub />);
  expect(screen.getByRole("heading", { name: "Choose your workspace" })).toBeVisible();
});

it("starts an application administrator with setup even without a membership", () => {
  env.appAdmin = true;
  env.organizations = [];
  env.data = null;
  render(<StartHub />);
  expect(screen.getByRole("heading", { name: "Application setup" })).toBeVisible();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
it("offers organization setup to a company administrator, without deployment authority", () => {
  env.orgAdmin = true;
  render(<StartHub />);
  expect(screen.getByRole("heading", { name: "Organization setup" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Application setup" })).not.toBeInTheDocument();
});

it("lets a member finish the walkthrough without configuring or running an agent", async () => {
  render(<StartHub />);
  await userEvent.click(screen.getByRole("button", { name: "Finish setup and open the app" }));
  expect(env.finish).toHaveBeenCalledWith({ completed: true }, expect.any(Object));
  expect(env.save).not.toHaveBeenCalled();
});

it("gives a fresh member a personal welcome instead of the administrator's configuration", () => {
  if (!env.data) throw new Error("missing fixture");
  env.data.completed = false;
  render(<StartHub />);
  expect(screen.getByRole("heading", { name: "Welcome to Acme" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Application setup" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Organization setup" })).not.toBeInTheDocument();
});

it("lets a member enter the trusted draft setup chat instead of blocking on administrator access", async () => {
  if (!env.data) throw new Error("Missing onboarding fixture");
  env.data.setup_agent = { id: "starter", name: "AgenticOS" };
  render(<StartHub />);
  expect(screen.getByText(/You can open the chat now/)).toBeVisible();
  expect(screen.queryByRole("combobox", { name: "Agent" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Open chat with AgenticOS" }));
  await waitFor(() => expect(env.push).toHaveBeenCalledOnce());
  const url = pushedUrl();
  expect(url.pathname).toBe("/chat");
  expect(url.searchParams.get("with")).toBe("starter");
  expect(url.searchParams.get("example")).toBe("meeting");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText("Can add a model")).not.toBeInTheDocument();
});

it("prefers an accessible published agent over setup guidance", async () => {
  if (!env.data) throw new Error("Missing onboarding fixture");
  env.data.setup_agent = { id: "starter", name: "AgenticOS" };
  env.data.agents = [{ id: "published", name: "Team agent" }];
  render(<StartHub />);
  await userEvent.click(screen.getByRole("button", { name: "Try this task" }));
  await waitFor(() => expect(env.push).toHaveBeenCalledOnce());
  expect(pushedUrl().searchParams.get("with")).toBe("published");
  expect(screen.queryByText(/You can open the chat now/)).not.toBeInTheDocument();
});

function pushedUrl(): URL {
  const destination = env.push.mock.calls[0]?.[0];
  if (typeof destination !== "string") throw new Error("No chat destination was pushed");
  return new URL(destination, "https://example.com");
}
