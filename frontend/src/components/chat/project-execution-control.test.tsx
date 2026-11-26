import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ProjectExecutionControl } from "./project-execution-control";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useChatControlsStore } from "@/stores/chat-controls-store";
const env = vi.hoisted(() => ({
  project: {
    data: "project" as string | null | undefined,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  },
  details: {
    data: { backend: "service", name: "Release planning" },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  },
  desktop: false,
}));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => env.details }));
vi.mock("@/hooks/use-projects", () => ({ useProjectOfConversation: () => env.project }));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => (env.desktop ? { kind: "desktop" } : null),
}));
vi.mock("@/lib/desktop/shell", () => ({ isDesktopShell: () => env.desktop }));
beforeEach(() => {
  env.project = { data: "project", isPending: false, isError: false, refetch: vi.fn() };
  env.desktop = false;
  env.details = {
    data: { backend: "service", name: "Release planning" },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  };
  useConversationStore.setState({ currentConversationId: "chat", pendingProjectId: null });
  useWorkOnStore.setState({
    executionByConversation: {},
    draftExecutionByScope: {},
    byConversation: {},
    draft: null,
    draftProjectKey: null,
  });
  useChatControlsStore.setState({ byScope: {} });
});
it("keeps project files visible and optional command pins collapsed", async () => {
  render(<ProjectExecutionControl agentCapabilities={["sandbox", "projects"]} />);
  expect(screen.getByRole("region", { name: "Release planning" })).toBeVisible();
  expect(screen.getByText(/The agent keeps its own tools/)).toBeVisible();
  expect(screen.getByText("Advanced command target").closest("details")).not.toHaveAttribute(
    "open",
  );
  expect(useWorkOnStore.getState().executionFor("chat")).toBeNull();
  await userEvent.click(screen.getByText("Advanced command target"));
  const automatic = screen.getByRole("radio", { name: "Automatic — let the agent choose" });
  expect(automatic).toBeChecked();
  for (const [label, target] of [
    ["Project sandbox only", "project"],
    ["Agent workspace only", "agent"],
  ]) {
    await userEvent.click(screen.getByRole("radio", { name: label }));
    expect(useWorkOnStore.getState().executionFor("chat")).toBe(target);
  }
  await userEvent.click(automatic);
  expect(useWorkOnStore.getState().executionFor("chat")).toBeNull();
});
it("explains the configured workspace without project choices outside a project", () => {
  env.project.data = null;
  render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByText(/uses its configured workspace/)).toBeVisible();
  expect(screen.queryByRole("radio")).toBeNull();
});
it("ignores another project draft and preserves local folder consent", () => {
  useConversationStore.setState({ currentConversationId: null, pendingProjectId: "new-project" });
  useWorkOnStore.getState().setExecution(null, "different-project", "project");
  const view = render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByText("Advanced command target").closest("details")).not.toHaveAttribute(
    "open",
  );
  env.desktop = true;
  act(() => useWorkOnStore.getState().set(null, { folder: "/allowed", mode: "read_only" }));
  view.rerender(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.queryByText("Advanced command target")).toBeNull();
  expect(screen.getByText(/folder allowed on this computer/)).toBeVisible();
});
it("offers shared files without implying command capability", () => {
  render(<ProjectExecutionControl agentCapabilities={["projects"]} />);
  expect(screen.queryByText("Advanced command target")).toBeNull();
  expect(screen.getByText(/available without command execution/)).toBeVisible();
});
it("shows loading and retries a failed project lookup", async () => {
  env.project.data = undefined;
  env.project.isPending = true;
  const view = render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByText(/Checking this chat/)).toBeVisible();
  expect(screen.queryByText("Advanced command target")).toBeNull();
  env.project.isPending = false;
  env.project.isError = true;
  view.rerender(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(env.project.refetch).toHaveBeenCalledOnce();
  expect(screen.getByRole("alert")).toBeVisible();
});
it("does not offer an absent project executor but can clear a remembered pin", async () => {
  useWorkOnStore.getState().setExecution("chat", "project", "project");
  env.details.data.backend = "state";
  render(<ProjectExecutionControl agentCapabilities={["sandbox", "projects"]} />);
  expect(screen.getByText(/This project has no command environment/)).toBeVisible();
  await userEvent.click(screen.getByText("Advanced command target"));
  const project = screen.getByRole("radio", { name: "Project sandbox only" });
  expect(project).toBeDisabled();
  expect(project).toBeChecked();
  await userEvent.click(screen.getByRole("radio", { name: "Automatic — let the agent choose" }));
  expect(useWorkOnStore.getState().executionFor("chat")).toBeNull();
});
it("waits for project metadata and retries failed details", async () => {
  env.details.isPending = true;
  const view = render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.queryByText("Advanced command target")).toBeNull();
  expect(screen.getByRole("region", { name: "Project files" })).toBeVisible();
  env.details.isPending = false;
  env.details.isError = true;
  view.rerender(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(env.details.refetch).toHaveBeenCalledOnce();
});
