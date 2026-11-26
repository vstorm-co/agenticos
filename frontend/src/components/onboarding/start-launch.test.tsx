import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartLaunch } from "./start-launch";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { Onboarding } from "@/lib/onboarding-api";
const env = vi.hoisted(() => ({
  starter: true,
  canUse: true,
  canConfigure: false,
  legacy: false,
  status: "ready",
  error: null as unknown,
  loading: false,
  canEdit: false,
  prepare: vi.fn(),
  retry: vi.fn(),
  push: vi.fn(),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: env.legacy
      ? [
          {
            id: "real-agent",
            name: "AgenticOS",
            slug: "agenticos",
            status: "published",
            is_starter: false,
          },
        ]
      : env.starter
        ? [
            {
              id: "real-agent",
              name: "Renamed AgenticOS",
              slug: "agenticos",
              is_starter: true,
              can_edit: env.canEdit,
            },
          ]
        : [{ id: "fake", name: "AgenticOS", slug: "impostor", is_starter: false }],
    error: env.error,
    isLoading: env.loading,
    refetch: env.retry,
  }),
}));
vi.mock("@/hooks/use-assistant", () => ({
  useAssistant: () => ({
    assistant: {
      name: "Architect",
      slug: "architect",
      can_use: env.canUse,
      can_configure: env.canConfigure,
      agent_id: "architect-id",
      status: env.status,
    },
    error: env.error,
    isLoading: env.loading,
    retry: env.retry,
  }),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: env.push }) }));
vi.mock("@/components/ui/avatar-face", () => ({ AvatarFace: () => null }));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({ prepare: { mutate: env.prepare, error: null, isPending: false } }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({ profiles: [], profilesStatus: "success" }),
}));
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({
    onChange,
    allowAdd,
  }: {
    onChange: (id: string) => void;
    allowAdd: boolean;
  }) => (
    <button onClick={() => onChange("shared-model")}>
      {allowAdd ? "Choose or add model" : "Choose existing model"}
    </button>
  ),
}));
const data: Onboarding = {
  organization_id: "org",
  organization_name: "Workspace",
  agents: [{ id: "real-agent", name: "Renamed AgenticOS" }],
  setup_agent: null,
  can_prepare: false,
  can_configure_model: false,
  completed: false,
  dismissed: false,
  snoozed_until: null,
  has_result: false,
  has_activity: false,
  goal: null,
  support_email: null,
  latest_conversation_id: null,
  latest_completed_at: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(env, {
    starter: true,
    legacy: false,
    canConfigure: false,
    canUse: true,
    status: "ready",
    error: null,
    loading: false,
    canEdit: false,
  });
  useArchitectAskStore.setState({ request: null });
});
it("opens the real renamed starter and opens Architect without submitting a prompt", async () => {
  render(<StartLaunch data={data} />);
  expect(screen.getByRole("heading", { name: "Renamed AgenticOS" })).toBeVisible();
  expect(screen.getByRole("link", { name: /Start with AgenticOS/ })).toHaveAttribute(
    "href",
    "/chat?with=real-agent",
  );
  expect(useArchitectAskStore.getState().request).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Build with Architect" }));
  expect(useArchitectAskStore.getState().request).toMatchObject({ text: "", openOnly: true });
  expect(env.push).toHaveBeenCalledWith("/chat");
});
it("does not offer a forbidden or disabled Architect or a lookalike starter", () => {
  env.starter = false;
  env.canUse = false;
  env.status = "disabled";
  render(<StartLaunch data={data} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Build with Architect" })).not.toBeInTheDocument();
  expect(screen.getByText(/not made this agent available/)).toBeVisible();
});
it("offers the server-authorized starter setup chat before publication", () => {
  render(
    <StartLaunch
      data={{ ...data, agents: [], setup_agent: { id: "real-agent", name: "AgenticOS" } }}
    />,
  );
  expect(screen.getByRole("link", { name: /Set up AgenticOS/ })).toHaveAttribute(
    "href",
    "/chat?with=real-agent",
  );
});
it("reports failed reads explicitly and lets the user retry", async () => {
  env.error = new Error("Read failed");
  render(<StartLaunch data={data} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  for (const button of screen.getAllByRole("button", { name: "Try again" }))
    await userEvent.click(button);
  expect(env.retry).toHaveBeenCalledTimes(2);
});

it("offers configuration only to an authorized Architect editor", () => {
  env.status = "needs_model";
  env.canConfigure = true;
  render(<StartLaunch data={data} />);
  expect(screen.getByRole("link", { name: "Configure Architect" })).toHaveAttribute(
    "href",
    "/agents/architect-id",
  );
  expect(screen.queryByRole("button", { name: "Build with Architect" })).not.toBeInTheDocument();
});

it("recognizes a published legacy starter only when the server allows it to run", () => {
  env.legacy = true;
  render(<StartLaunch data={data} />);
  expect(screen.getByRole("link", { name: /Start with AgenticOS/ })).toHaveAttribute(
    "href",
    "/chat?with=real-agent",
  );
});

it("lets an authorized owner explicitly prepare a missing starter with a shared model", async () => {
  env.starter = false;
  render(<StartLaunch data={{ ...data, agents: [], can_prepare: true }} />);
  expect(env.prepare).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Connect a model" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Choose or add model" })).not.toBeInTheDocument();
  const prepare = screen.getByRole("button", { name: "Prepare a text assistant" });
  expect(prepare).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Choose existing model" }));
  await userEvent.click(prepare);
  expect(env.prepare).toHaveBeenCalledWith("shared-model", { onSuccess: expect.any(Function) });
});

it("keeps unavailable-starter configuration behind its resource edit grant", () => {
  const { rerender } = render(<StartLaunch data={{ ...data, agents: [] }} />);
  expect(screen.queryByRole("link", { name: "Configure AgenticOS" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Connect a model" })).not.toBeInTheDocument();
  env.canEdit = true;
  rerender(<StartLaunch data={{ ...data, agents: [] }} />);
  expect(screen.getByRole("link", { name: "Configure AgenticOS" })).toHaveAttribute(
    "href",
    "/agents/real-agent",
  );
  expect(
    screen.queryByRole("link", { name: /Start with AgenticOS|Set up AgenticOS/ }),
  ).not.toBeInTheDocument();
});
