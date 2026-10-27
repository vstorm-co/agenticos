import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ProjectSandboxChoice, ProjectSandboxSummary } from "./project-sandbox-choice";
import { listSandboxConnections } from "@/lib/sandbox-connections-api";

vi.mock("@/lib/sandbox-connections-api", () => ({ listSandboxConnections: vi.fn() }));
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
      project={{ backend: "service", sandbox_connection_name: "Local sandbox", runtime: "python" }}
    />,
  );
  expect(screen.getByText("Local sandbox")).toBeInTheDocument();
  expect(screen.getByText("python")).toBeInTheDocument();
  expect(
    screen.getByText(/replaces the sandbox configured on the answering agent/),
  ).toBeInTheDocument();
  rerender(
    <ProjectSandboxSummary
      project={{ backend: "service", sandbox_connection_name: null, runtime: null }}
    />,
  );
  expect(screen.getByText("Configured sandbox")).toBeInTheDocument();
  rerender(<ProjectSandboxSummary project={{ backend: "state", runtime: null }} />);
  expect(screen.getByText("Stored files only")).toBeInTheDocument();
});
