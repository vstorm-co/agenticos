import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { RoleNavigationEditor } from "./role-navigation-editor";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { OrgRole } from "@/types/organization";
import { Perm, type RoleCatalog } from "@/types/permissions";
import type { RoleNavigationPolicy } from "@/types/role-navigation";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), patch: vi.fn() } }));

const PERMISSIONS = [
  Perm.agentsView,
  Perm.agentsRun,
  Perm.workflowsView,
  Perm.datasetsView,
  Perm.artifactsView,
  Perm.projectsView,
  Perm.collectionsView,
  Perm.tablesView,
  Perm.skillsView,
  Perm.contextView,
];
const ROLES: OrgRole[] = ["owner", "admin", "builder", "operator", "member", "viewer"];
const CATALOG: RoleCatalog = {
  all_permissions: PERMISSIONS,
  resource_permissions: PERMISSIONS,
  roles: ROLES.map((name) => ({
    name,
    permissions: [
      ...PERMISSIONS.map((permission) => ({ permission, scope: "shared" as const })),
      {
        permission: Perm.runsView,
        scope: name === "member" ? ("none" as const) : ("all" as const),
      },
    ],
  })),
};
const POLICY: RoleNavigationPolicy = {
  hidden_items: { owner: [], admin: [], builder: [], operator: [], member: ["skills"], viewer: [] },
  configurable_items: [
    "chat",
    "inbox",
    "agentMessages",
    "allApps",
    "agents",
    "workflows",
    "routines",
    "datasets",
    "allProjects",
    "knowledgeBases",
    "tables",
    "skills",
    "context",
    "documents",
    "activity",
    "failureLearning",
    "backgroundWork",
    "connectors",
    "groups",
  ],
  editable_roles: ["admin", "builder", "operator", "member", "viewer"],
};
let client: QueryClient;

function view(organizationId = "org-a") {
  return (
    <QueryClientProvider client={client}>
      <RoleNavigationEditor organizationId={organizationId} catalog={CATALOG} />
    </QueryClientProvider>
  );
}
async function renderEditor() {
  const result = render(view());
  await screen.findByRole("combobox", { name: "Role" });
  return result;
}
async function selectRole(name: string) {
  await userEvent.click(screen.getByRole("combobox", { name: "Role" }));
  await userEvent.click(screen.getByRole("option", { name }));
}
function preview() {
  return within(screen.getByRole("complementary", { name: "Sidebar preview" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useOrgStore.setState({ activeOrgId: "org-a" });
  vi.mocked(apiClient.get).mockResolvedValue(POLICY);
  vi.mocked(apiClient.patch).mockImplementation(async (_path, body) => ({
    ...POLICY,
    hidden_items: {
      ...POLICY.hidden_items,
      member: (body as { hidden_items: string[] }).hidden_items,
    },
  }));
});

describe("role navigation editor", () => {
  it("shows a loading state before the policy is available", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    render(view());
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("reports a policy error and retries without offering edits", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("Policy service offline"));
    render(view());
    expect(await screen.findByRole("alert")).toHaveTextContent("Policy service offline");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("combobox", { name: "Role" });
  });

  it("previews the intersection of role permissions and saved visibility", async () => {
    await renderEditor();
    expect(screen.getByRole("combobox", { name: "Role" })).toHaveTextContent("Member");
    expect(preview().getByText("Agents")).toBeInTheDocument();
    expect(preview().queryByText("Skills")).not.toBeInTheDocument();
    expect(preview().queryByText("Activity")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Show Activity" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Show Activity" })).not.toBeChecked();
    const dashboard = screen.getByRole("checkbox", { name: `Show ${messages.nav.dashboard}` });
    expect(dashboard).toBeChecked();
    expect(dashboard).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Show Organizations" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save sidebar" })).toBeDisabled();
  });

  it("updates the preview and saves only the selected role after an explicit click", async () => {
    await renderEditor();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show Agents" }));
    expect(preview().queryByText("Agents")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Role" })).toBeDisabled();
    expect(apiClient.patch).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Save sidebar" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(
        "/roles/navigation/member",
        { hidden_items: ["skills", "agents"] },
        { headers: { "X-Organization-Id": "org-a" } },
      ),
    );
    await screen.findByText("Sidebar saved");
    expect(screen.getByRole("combobox", { name: "Role" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Save sidebar" })).toBeDisabled();
  });

  it("can show a previously hidden item", async () => {
    await renderEditor();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show Skills" }));
    expect(preview().getByText("Skills")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save sidebar" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(
        "/roles/navigation/member",
        { hidden_items: [] },
        { headers: { "X-Organization-Id": "org-a" } },
      ),
    );
  });

  it("keeps defaults as a draft until saved and allows discarding changes", async () => {
    await renderEditor();
    await userEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(preview().getByText("Skills")).toBeInTheDocument();
    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Reset to defaults" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(preview().queryByText("Skills")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Role" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Discard changes" })).not.toBeInTheDocument();
  });

  it("replaces an existing hidden item and removes empty preview sections", async () => {
    await renderEditor();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show Skills" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Show All apps" }));
    expect(preview().queryByText("Apps")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save sidebar" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Save sidebar" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(
        "/roles/navigation/member",
        { hidden_items: ["allApps"] },
        { headers: { "X-Organization-Id": "org-a" } },
      ),
    );
  });

  it("preserves the selection and draft after a refused save", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Role change refused"));
    await renderEditor();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show Agents" }));
    await userEvent.click(screen.getByRole("button", { name: "Save sidebar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Role change refused");
    expect(screen.getByRole("checkbox", { name: "Show Agents" })).not.toBeChecked();
    expect(screen.getByRole("combobox", { name: "Role" })).toHaveTextContent("Member");
    expect(screen.getByRole("button", { name: "Save sidebar" })).toBeEnabled();
  });

  it("retains unsaved choices when a background policy refresh fails", async () => {
    await renderEditor();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show Agents" }));
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Policy refresh failed"));
    await act(async () => {
      await client.invalidateQueries({ queryKey: qk.organizations.roleNavigation("org-a") });
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Policy refresh failed");
    expect(screen.getByRole("checkbox", { name: "Show Agents" })).not.toBeChecked();
    expect(screen.getByRole("combobox", { name: "Role" })).toHaveTextContent("Member");
    expect(screen.getByRole("button", { name: "Save sidebar" })).toBeEnabled();
  });

  it("disables editing during a save", async () => {
    vi.mocked(apiClient.patch).mockReturnValue(new Promise(() => {}));
    await renderEditor();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show Agents" }));
    await userEvent.click(screen.getByRole("button", { name: "Save sidebar" }));
    expect(screen.getByRole("button", { name: "Save sidebar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reset to defaults" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Show Skills" })).toBeDisabled();
  });

  it("protects the owner role while allowing a read-only preview", async () => {
    await renderEditor();
    await selectRole("Owner");
    expect(screen.getByText(/Owner sidebar stays available/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save sidebar" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Show Agents" })).toBeDisabled();
    expect(preview().getByText("Skills")).toBeInTheDocument();
  });

  it("does not render save controls for roles the server does not allow editing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ ...POLICY, editable_roles: [] });
    await renderEditor();
    expect(screen.getByText(/You can preview this role/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save sidebar" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Show Agents" })).toBeDisabled();
    await selectRole("Admin");
    expect(preview().getByText("Activity")).toBeInTheDocument();
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("discards a prior organization's draft before displaying a new organization", async () => {
    const rendered = await renderEditor();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show Agents" }));
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    expect(screen.queryByRole("button", { name: "Save sidebar" })).not.toBeInTheDocument();
    vi.mocked(apiClient.get).mockResolvedValue({
      ...POLICY,
      hidden_items: { ...POLICY.hidden_items, member: [] },
    });
    rendered.rerender(view("org-b"));
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Show Agents" })).toBeChecked(),
    );
    expect(screen.getByRole("button", { name: "Save sidebar" })).toBeDisabled();
    expect(preview().getByText("Skills")).toBeInTheDocument();
    expect(apiClient.patch).not.toHaveBeenCalled();
  });
});
