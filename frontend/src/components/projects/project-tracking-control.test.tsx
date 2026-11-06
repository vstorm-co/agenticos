import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { trackingProject as project } from "@/test-utils/project-tracking";
import type { ProjectTracking, ProjectTrackingCreate } from "@/lib/project-tracking-api";
import { ProjectTrackingControl } from "./project-tracking-control";
const state = vi.hoisted(() => ({
  loading: false,
  error: null as Error | null,
  data: null as ProjectTracking | null,
  allowed: true,
  save: vi.fn(),
  retry: vi.fn(),
}));
vi.mock("@/hooks/use-project-tracking", () => ({
  useProjectTracking: () => ({
    data: state.data,
    error: state.error,
    isLoading: state.loading,
    refetch: state.retry,
    create: { mutate: state.save, isPending: false },
  }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.allowed }),
}));
vi.mock("./project-tracking-dialog", () => ({
  ProjectTrackingDialog: ({
    onCreate,
    onClose,
  }: {
    onCreate: (data: ProjectTrackingCreate, close: () => void) => void;
    onClose: () => void;
  }) => (
    <button
      onClick={() =>
        onCreate(
          {
            base_agent_id: "a",
            base_version_id: "v",
            source_review_token: "review",
            publish_and_start: true,
            agent_name: "Tracker",
            table_name: "Tasks",
            table_visibility: "private",
            interval_seconds: 86400,
          },
          onClose,
        )
      }
    >
      Confirm setup
    </button>
  ),
}));
beforeEach(() => {
  state.loading = false;
  state.error = null;
  state.data = null;
  state.allowed = true;
  state.save.mockReset();
  state.retry.mockReset();
});
it("offers creation only to an entitled caller and retains loading/refusal states", () => {
  state.allowed = false;
  const view = render(<ProjectTrackingControl project={project} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  state.allowed = true;
  state.loading = true;
  view.rerender(<ProjectTrackingControl project={project} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("opens review and waits for successful creation before closing", async () => {
  render(<ProjectTrackingControl project={project} />);
  await userEvent.click(screen.getByRole("button", { name: "Keep project on track" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm setup" }));
  const call = state.save.mock.calls[0];
  expect(call?.[0]).toEqual(expect.objectContaining({ publish_and_start: true }));
  call?.[1].onSuccess();
});
it("links to the installed table", () => {
  state.data = {
    id: "setup",
    project_id: "launch",
    agent_id: "agent",
    agent_version_id: "v",
    trigger_id: "routine",
    table_id: "tasks",
    conversation_id: "chat",
  };
  render(<ProjectTrackingControl project={project} />);
  expect(screen.getByRole("link", { name: "Task table" })).toHaveAttribute("href", "/tables/tasks");
});
it("retries a failed tracker lookup", async () => {
  state.error = new Error("Offline");
  render(<ProjectTrackingControl project={project} />);
  await userEvent.click(screen.getByRole("button", { name: "Retry project tracker" }));
  expect(state.retry).toHaveBeenCalledOnce();
});
