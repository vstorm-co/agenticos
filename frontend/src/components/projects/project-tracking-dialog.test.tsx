import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { trackingProject as project } from "@/test-utils/project-tracking";
import type { ProjectTrackingReview } from "@/lib/project-tracking-api";
import { ProjectTrackingDialog } from "./project-tracking-dialog";
import type { AgentAvatarProps } from "@/components/agents/agent-avatar";

vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ agentId, slug, hasAvatar, colorSlot }: AgentAvatarProps) => (
    <span
      data-testid="agent-avatar"
      data-id={agentId}
      data-slug={slug}
      data-uploaded={String(hasAvatar)}
      data-color={colorSlot}
    />
  ),
}));

const state = vi.hoisted(() => ({
  loading: false,
  agentsError: null as Error | null,
  reviewError: null as Error | null,
  fetching: false,
  retry: vi.fn(),
  retryReview: vi.fn(),
  review: {
    review_token: "review-one",
    base_agent_id: "planner",
    base_version_id: "v1",
    base_agent_name: "Planner",
    resources: ["Knowledge · selected"],
    accounts: ["Work account · exact"],
    unavailable_sources: [],
  } as ProjectTrackingReview,
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: [
      {
        id: "planner",
        name: "Planner",
        slug: "planner",
        has_avatar: true,
        avatar_color: 4,
        current_version_id: "v1",
        status: "published",
        can_run: true,
      },
      { id: "draft", name: "Draft", current_version_id: null, status: "draft", can_run: true },
    ],
    error: state.agentsError,
    isLoading: state.loading,
    refetch: state.retry,
  }),
}));
vi.mock("@/hooks/use-project-tracking", () => ({
  useProjectTrackingReview: (_project: string, agent: string | null) => ({
    data: agent ? state.review : undefined,
    error: state.reviewError,
    isFetching: state.fetching,
    refetch: state.retryReview,
  }),
}));

const save = vi.fn();
const close = vi.fn();
function mount(pending = false) {
  return render(
    <ProjectTrackingDialog project={project} pending={pending} onCreate={save} onClose={close} />,
  );
}
async function choose() {
  await userEvent.click(screen.getByRole("combobox", { name: "Source agent you can edit" }));
  await userEvent.click(screen.getByRole("option", { name: "Planner" }));
}
beforeEach(() => {
  save.mockReset();
  close.mockReset();
  state.retry.mockReset();
  state.retryReview.mockReset();
  state.loading = false;
  state.agentsError = null;
  state.reviewError = null;
  state.fetching = false;
  state.review.review_token = "review-one";
  state.review.unavailable_sources = [];
});
it("shows the source agent portrait in the options and the selected value", async () => {
  mount();
  const selector = screen.getByRole("combobox", { name: "Source agent you can edit" });
  await userEvent.click(selector);
  const option = screen.getByRole("option", { name: "Planner" });
  const portrait = within(option).getByTestId("agent-avatar");
  expect(portrait).toHaveAttribute("data-id", "planner");
  expect(portrait).toHaveAttribute("data-slug", "planner");
  expect(portrait).toHaveAttribute("data-uploaded", "true");
  expect(portrait).toHaveAttribute("data-color", "4");
  await userEvent.click(option);
  expect(within(selector).getByTestId("agent-avatar")).toHaveAttribute("data-id", "planner");
});
it("requires explicit publication consent and sends the exact reviewed version and accounts", async () => {
  mount();
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeDisabled();
  await choose();
  expect(screen.getByText("Work account · exact")).toBeVisible();
  expect(screen.getByText("Knowledge · selected")).toBeVisible();
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: /I approve these sources/ }));
  await userEvent.click(screen.getByRole("button", { name: "Publish and start" }));
  expect(save).toHaveBeenCalledWith(
    {
      base_agent_id: "planner",
      base_version_id: "v1",
      source_review_token: "review-one",
      publish_and_start: true,
      agent_name: "Launch tracker",
      table_name: "Launch tasks",
      table_visibility: "private",
      interval_seconds: 86400,
    },
    close,
  );
  expect(close).not.toHaveBeenCalled();
});
it("drops confirmation when a refreshed review describes different authority", async () => {
  const view = mount();
  await choose();
  await userEvent.click(screen.getByRole("checkbox", { name: /I approve these sources/ }));
  state.review.review_token = "review-two";
  view.rerender(
    <ProjectTrackingDialog project={project} pending={false} onCreate={save} onClose={close} />,
  );
  expect(screen.getByRole("checkbox", { name: /I approve these sources/ })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeDisabled();
});
it("inherits project access and rejects empty names", async () => {
  mount();
  await choose();
  await userEvent.click(screen.getByRole("checkbox", { name: /I approve these sources/ }));
  expect(
    screen.queryByRole("checkbox", { name: "Make the task table visible to the organization" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Task table name"), { target: { value: "   " } });
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Task table name"), { target: { value: "Team tasks" } });
  await userEvent.click(screen.getByRole("button", { name: "Publish and start" }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({ table_visibility: "private", table_name: "Team tasks" }),
    close,
  );
});
it("cannot approve unavailable sources", async () => {
  state.review.unavailable_sources = ["Work account"];
  mount();
  await choose();
  expect(screen.getByRole("status")).toHaveTextContent("Work account");
  expect(screen.getByRole("checkbox", { name: /I approve these sources/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeDisabled();
});
it.each(["agents", "review"])("shows and retries a %s load failure", async (failure) => {
  if (failure === "agents") state.agentsError = new Error("Offline");
  else state.reviewError = new Error("Offline");
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(failure === "agents" ? state.retry : state.retryReview).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeDisabled();
});
it("keeps pending setup visible and cannot cancel a submitted installation", async () => {
  mount(true);
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByLabelText("Task table name")).toBeDisabled();
  await userEvent.keyboard("{Escape}");
  expect(close).not.toHaveBeenCalled();
});
it("can cancel before publishing", async () => {
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(close).toHaveBeenCalledOnce();
});
it("waits for agent and source loading without enabling publication", async () => {
  state.loading = true;
  state.fetching = true;
  mount();
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeDisabled();
});

it("uses the edited tracker name in the reviewed installation", async () => {
  mount();
  await choose();
  fireEvent.change(screen.getByLabelText("New tracker agent"), {
    target: { value: "Release tracker" },
  });
  await userEvent.click(screen.getByRole("checkbox", { name: /I approve these sources/ }));
  await userEvent.click(screen.getByRole("button", { name: "Publish and start" }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({ agent_name: "Release tracker" }),
    close,
  );
});

it("can revoke source approval before starting a tracker", async () => {
  mount();
  await choose();
  const consent = screen.getByRole("checkbox", { name: /I approve these sources/ });
  await userEvent.click(consent);
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeEnabled();
  await userEvent.click(consent);
  expect(screen.getByRole("button", { name: "Publish and start" })).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
});

it("closes an unsubmitted tracker with Escape", async () => {
  mount();
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalledOnce();
});
