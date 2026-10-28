import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ProjectSandboxChoice, ProjectSandboxSummary } from "./project-sandbox-choice";
import { listSandboxConnections } from "@/lib/sandbox-connections-api";

vi.mock("@/lib/sandbox-connections-api", () => ({ listSandboxConnections: vi.fn() }));
const moveWorkspace = { isPending: false, mutateAsync: vi.fn() };
vi.mock("@/hooks/use-projects", () => ({ useProject: () => ({ moveWorkspace }) }));
const project = {
  id: "p1",
  name: "Wiki",
  description: null,
  instructions: "",
  default_agent_id: null,
  default_agent_name: null,
  owner_user_id: null,
  visibility: "private" as const,
  chat_count: 0,
  last_active_at: null,
  shared_groups: [],
  can_use: true,
  can_edit: true,
  created_at: null,
  updated_at: null,
};
let allowed = true;
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => allowed }) }));
function Harness() {
  const [value, setValue] = useState("auto");
  return <ProjectSandboxChoice value={value} onChange={setValue} enabled />;
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  allowed = true;
  vi.mocked(listSandboxConnections).mockResolvedValue([
    {
      id: "local",
      name: "Local sandbox",
      kind: "docker",
      is_default: true,
      is_active: true,
      base_url: null,
      secret_id: null,
      default_runtime: null,
      created_at: "2026-10-27",
      updated_at: null,
    },
    {
      id: "cloud",
      name: "Cloud sandbox",
      kind: "daytona",
      is_default: false,
      is_active: true,
      base_url: null,
      secret_id: null,
      default_runtime: null,
      created_at: "2026-10-27",
      updated_at: null,
    },
    {
      id: "off",
      name: "Offline host",
      kind: "docker",
      is_default: false,
      is_active: false,
      base_url: null,
      secret_id: null,
      default_runtime: null,
      created_at: "2026-10-27",
      updated_at: null,
    },
  ]);
});
it("offers active named sandbox connections and an explicit files-only mode", async () => {
  mount();
  await screen.findByText("Automatic · Local sandbox");
  await userEvent.click(screen.getByRole("combobox", { name: "Project sandbox" }));
  expect(screen.queryByRole("option", { name: "Offline host" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("option", { name: "Cloud sandbox" }));
  expect(screen.getByRole("combobox")).toHaveTextContent("Cloud sandbox");
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Stored files only" }));
  expect(screen.getByText(/cannot execute code here/)).toBeInTheDocument();
});
it("keeps automatic and storage choices available without connection-list permission", async () => {
  allowed = false;
  mount();
  await userEvent.click(screen.getByRole("combobox"));
  expect(screen.getByRole("option", { name: "Automatic" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Stored files only" })).toBeInTheDocument();
  expect(listSandboxConnections).not.toHaveBeenCalled();
});
it("reports a failed list rather than implying no sandbox exists", async () => {
  vi.mocked(listSandboxConnections).mockRejectedValue(new Error("offline"));
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load sandbox connections");
});
it("shows which shared sandbox a project actually uses and its runtime", () => {
  const { rerender } = render(
    <ProjectSandboxSummary
      project={{
        ...project,
        backend: "service",
        sandbox_connection_name: "Local sandbox",
        runtime: "python",
      }}
    />,
  );
  expect(screen.getByText("Local sandbox")).toBeInTheDocument();
  expect(screen.getByText("python")).toBeInTheDocument();
  expect(
    screen.getByText(/replaces the sandbox configured on the answering agent/),
  ).toBeInTheDocument();
  rerender(
    <ProjectSandboxSummary
      project={{ ...project, backend: "service", sandbox_connection_name: null, runtime: null }}
    />,
  );
  expect(screen.getByText("Configured sandbox")).toBeInTheDocument();
  rerender(<ProjectSandboxSummary project={{ ...project, backend: "state", runtime: null }} />);
  expect(screen.getByText("Stored files only")).toBeInTheDocument();
});

it("explains storage, shared access and code execution beside the setting", async () => {
  render(<ProjectSandboxSummary project={{ ...project, backend: "state", runtime: null }} />);
  await userEvent.click(screen.getByText("How project files and code execution work"));
  expect(screen.getByText(/Existing tool approval requirements still apply/)).toBeVisible();
  expect(screen.getByText(/shared with everyone who can access this project/)).toBeVisible();
});

it("confirms an explicit destination before queuing an existing project's transfer", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProjectSandboxSummary project={{ ...project, backend: "state", runtime: null }} />
    </QueryClientProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Change sandbox" }));
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: "Cloud sandbox" }));
  expect(moveWorkspace.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Move project files" }));
  const { within } = await import("@testing-library/react");
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Move project files" }),
  );
  expect(moveWorkspace.mutateAsync).toHaveBeenCalledWith("cloud");
});

it("shows transfer progress and keeps the selected source while writes pause", () => {
  render(
    <ProjectSandboxSummary
      project={{
        ...project,
        backend: "service",
        runtime: null,
        sandbox_connection_name: "Local sandbox",
        workspace_move: {
          job_id: "j",
          status: "running",
          target_name: "Cloud sandbox",
          copied_files: 2,
          total_files: 5,
          copied_bytes: 20,
        },
      }}
    />,
  );
  expect(screen.getByText("Local sandbox")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("2 of 5 files copied");
  expect(screen.queryByRole("button", { name: "Change sandbox" })).not.toBeInTheDocument();
});

it("preserves a failed transfer's source and gives viewers no edit control", () => {
  render(
    <ProjectSandboxSummary
      project={{
        ...project,
        can_edit: false,
        backend: "state",
        runtime: null,
        workspace_move: {
          job_id: "j",
          status: "dead",
          target_name: "Cloud",
          copied_files: 0,
          total_files: 5,
          copied_bytes: 0,
        },
      }}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("previous workspace is still selected");
  expect(screen.queryByRole("button", { name: "Change sandbox" })).not.toBeInTheDocument();
});

it("acknowledges a verified activation and refuses moving to the already selected connection", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProjectSandboxSummary
        project={{
          ...project,
          backend: "service",
          runtime: null,
          sandbox_connection_id: "cloud",
          sandbox_connection_name: "Cloud sandbox",
          workspace_move: {
            job_id: "j",
            status: "succeeded",
            target_name: "Cloud sandbox",
            copied_files: 5,
            total_files: 5,
            copied_bytes: 100,
          },
        }}
      />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("new workspace activated");
  await userEvent.click(screen.getByRole("button", { name: "Change sandbox" }));
  expect(screen.getByRole("button", { name: "Move project files" })).toBeDisabled();
});
