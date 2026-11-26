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
  details: { data: { backend: "service" }, isPending: false, isError: false, refetch: vi.fn() },
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
    data: { backend: "service" },
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
it("defaults a project chat to its project and separately chooses the agent executor", async () => {
  render(<ProjectExecutionControl agentCapabilities={["sandbox", "projects"]} />);
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeChecked();
  await userEvent.click(screen.getByRole("radio", { name: "Agent workspace" }));
  expect(useWorkOnStore.getState().executionFor("chat")).toBe("agent");
  expect(screen.getByText(/Choosing project context or files does not switch/)).toBeVisible();
});
it("does not infer a project for ordinary chats from old file origins", () => {
  env.project.data = null;
  render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeDisabled();
  expect(screen.getByRole("radio", { name: "Agent workspace" })).toBeChecked();
  expect(screen.getByText(/Start a chat in a project/)).toBeVisible();
});
it("uses only the matching project draft and preserves local folder consent", async () => {
  useConversationStore.setState({ currentConversationId: null, pendingProjectId: "new-project" });
  useWorkOnStore.getState().setExecution(null, "different-project", "agent");
  const view = render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeChecked();
  env.desktop = true;
  act(() => useWorkOnStore.getState().set(null, { folder: "/allowed", mode: "read_only" }));
  view.rerender(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeDisabled();
  expect(screen.getByText(/folder allowed on this computer/)).toBeVisible();
});
it("offers files-only context without pretending commands are available", () => {
  render(<ProjectExecutionControl agentCapabilities={["projects"]} />);
  expect(screen.queryByRole("radio")).toBeNull();
  expect(screen.getByText(/has no command execution capability/)).toBeVisible();
});
it("does not offer a project choice while its identity is loading or failed", async () => {
  env.project.data = undefined;
  env.project.isPending = true;
  const view = render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeDisabled();
  expect(screen.getByText(/Checking this chat/)).toBeVisible();
  expect(screen.getByRole("radio", { name: "Agent workspace" })).not.toBeChecked();
  env.project.isPending = false;
  env.project.isError = true;
  view.rerender(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(env.project.refetch).toHaveBeenCalledOnce();
  expect(screen.getByRole("alert")).toBeVisible();
});

it("defaults files-only projects to Agent and explains the separate files", () => {
  env.details.data.backend = "state";
  render(<ProjectExecutionControl agentCapabilities={["sandbox", "projects"]} />);
  expect(screen.getByRole("radio", { name: "Agent workspace" })).toBeChecked();
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeDisabled();
  expect(screen.getByText(/This project only stores files/)).toBeVisible();
  expect(useWorkOnStore.getState().executionFor("chat")).toBeNull();
});

it("retains an explicit Project choice after the project moves to stored files", async () => {
  useWorkOnStore.getState().setExecution("chat", "project", "project");
  env.details.data.backend = "state";
  render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeChecked();
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeDisabled();
  expect(useWorkOnStore.getState().executionFor("chat")).toBe("project");
  await userEvent.click(screen.getByRole("radio", { name: "Agent workspace" }));
  expect(useWorkOnStore.getState().executionFor("chat")).toBe("agent");
});

it("refuses unknown project execution until metadata is checked", async () => {
  env.details.isPending = true;
  const view = render(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  expect(screen.getByRole("radio", { name: "Project workspace" })).toBeDisabled();
  expect(screen.getByRole("radio", { name: "Agent workspace" })).not.toBeChecked();
  env.details.isPending = false;
  env.details.isError = true;
  view.rerender(<ProjectExecutionControl agentCapabilities={["sandbox"]} />);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(env.details.refetch).toHaveBeenCalledOnce();
});
