import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { RecordAccessDialog } from "./record-access-dialog";
import { TableRowAccess } from "./table-row-access";
import { apiClient } from "@/lib/api-client";
import type { ColumnDef, RowPolicy, TableRead } from "@/types/tables";
import type { RecordAccess } from "@/lib/table-record-access-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks", () => ({
  useMembers: () => ({
    members: [
      {
        id: "m1",
        organization_id: "org",
        user_id: "user-1",
        role: "viewer",
        email: "ada@example.com",
        full_name: "Ada",
        avatar_url: null,
        avatar_color: null,
        joined_at: "2026-01-01T00:00:00Z",
        source: "manual",
      },
    ],
  }),
  useGroups: () => ({
    groups: [
      {
        id: "group-1",
        organization_id: "org",
        name: "Support",
        description: null,
        icon: null,
        monthly_budget_usd: null,
        member_count: 1,
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
  }),
}));

const access: RecordAccess = { table_id: "table", record_id: "row", grants: [] };
const table: TableRead = {
  id: "table",
  name: "Orders",
  description: null,
  visibility: "org",
  owner_user_id: "owner",
  schema_version: 1,
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  can_edit: true,
  can_manage: true,
  can_restore: false,
  can_manage_row_access: true,
  row_policy_valid: true,
  columns: [],
  row_policy: null,
};
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeAll(() => {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
});
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(access);
  vi.mocked(apiClient.put).mockResolvedValue(access);
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("row access", () => {
  it("saves an expiring Read grant for a person and clears the submitted fields", async () => {
    const user = userEvent.setup();
    render(<RecordAccessDialog tableId="table" recordId="row" />, { wrapper });
    await user.click(screen.getByRole("button", { name: "Row access" }));
    await screen.findByText("No explicit grants. Table and row rules still apply.");
    expect(screen.getByRole("button", { name: "Save grant" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("button", { name: "Save grant" }).closest("form")!);
    expect(apiClient.put).not.toHaveBeenCalled();
    await user.click(screen.getByRole("combobox", { name: "Person or group" }));
    await user.click(await screen.findByRole("option", { name: /Ada/ }));
    await user.click(screen.getByRole("combobox", { name: "Permission" }));
    await user.click(await screen.findByRole("option", { name: "Write" }));
    await user.click(screen.getByRole("combobox", { name: "Permission" }));
    await user.click(await screen.findByRole("option", { name: "Read" }));
    const expiry = screen.getByLabelText("Expires (optional)");
    const chosenExpiry = "2030-05-01T10:30";
    fireEvent.change(expiry, { target: { value: chosenExpiry } });
    await user.click(screen.getByRole("button", { name: "Save grant" }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/tables/table/records/row/access/grants", {
        subject_user_id: "user-1",
        level: "read",
        expires_at: new Date(chosenExpiry).toISOString(),
      }),
    );
    await waitFor(() => expect(expiry).toHaveValue(""));
    expect(screen.getByRole("button", { name: "Save grant" })).toBeDisabled();
    expect(toast.success).toHaveBeenCalled();
  });

  it("retains a person's expiry when upgrading to Write and revokes their grant", async () => {
    const expires = "2030-05-01T10:30:00Z";
    vi.mocked(apiClient.get).mockResolvedValue({
      ...access,
      grants: [
        {
          id: "person-grant",
          subject_user_id: "user-1",
          subject_email: "ada@example.com",
          subject_group_id: null,
          subject_group_name: null,
          level: "read",
          expires_at: expires,
        },
        {
          id: "expired-grant",
          subject_user_id: null,
          subject_email: null,
          subject_group_id: "expired-group",
          subject_group_name: null,
          level: "write",
          expires_at: "2000-01-01T00:00:00Z",
        },
        {
          id: "unnamed-person-grant",
          subject_user_id: "user-2",
          subject_email: null,
          subject_group_id: null,
          subject_group_name: null,
          level: "read",
          expires_at: null,
        },
      ],
    });
    const user = userEvent.setup();
    render(<RecordAccessDialog tableId="table" recordId="row" />, { wrapper });
    await user.click(screen.getByRole("button", { name: "Row access" }));
    const picker = await screen.findByRole("combobox", { name: "Permission for ada@example.com" });
    expect(screen.getByRole("combobox", { name: "Permission for expired-group" })).toBeDisabled();
    expect(screen.getByText("Expired — add the grant again to renew it.")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Permission for user-2" })).toBeEnabled();
    expect(screen.getByText(/^Expires \d/)).toBeVisible();
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "Write" }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/tables/table/records/row/access/grants", {
        subject_user_id: "user-1",
        level: "write",
        expires_at: expires,
      }),
    );
    const remove = screen.getByRole("button", { name: "Remove access for ada@example.com" });
    await waitFor(() => expect(remove).toBeEnabled());
    await user.click(remove);
    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith(
        "/tables/table/records/row/access/grants/user-1",
      ),
    );
  });

  it("shows a refused access read instead of presenting an empty grant list", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Access is unavailable"));
    render(<RecordAccessDialog tableId="table" recordId="row" />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: "Row access" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Access is unavailable");
    expect(screen.queryByRole("button", { name: "Save grant" })).not.toBeInTheDocument();
  });

  it("shares a row with a group as Write, through the row namespace", async () => {
    const user = userEvent.setup();
    render(<RecordAccessDialog tableId="table" recordId="row" />, { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Row access" }));
    await screen.findByText("No explicit grants. Table and row rules still apply.");
    await user.click(screen.getByRole("combobox", { name: "Person or group" }));
    await user.click(await screen.findByRole("option", { name: "Support" }));
    await user.click(screen.getByRole("combobox", { name: "Permission" }));
    await user.click(await screen.findByRole("option", { name: "Write" }));
    await user.click(screen.getByRole("button", { name: "Save grant" }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/tables/table/records/row/access/grants", {
        subject_group_id: "group-1",
        level: "write",
        expires_at: null,
      }),
    );
    expect(screen.getByText(/does not allow deletion/)).toBeVisible();
  });

  it("downgrades Read/Write and revokes group access using the group endpoint", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      ...access,
      grants: [
        {
          id: "grant",
          subject_user_id: null,
          subject_email: null,
          subject_group_id: "group-1",
          subject_group_name: "Support",
          level: "write",
          expires_at: null,
        },
      ],
    });
    const user = userEvent.setup();
    render(<RecordAccessDialog tableId="table" recordId="row" />, { wrapper });
    await user.click(screen.getByRole("button", { name: "Row access" }));
    const picker = await screen.findByRole("combobox", { name: "Permission for Support" });
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "Read" }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/tables/table/records/row/access/grants", {
        subject_group_id: "group-1",
        level: "read",
        expires_at: null,
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Remove access for Support" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Remove access for Support" }));
    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith(
        "/tables/table/records/row/access/group-grants/group-1",
      ),
    );
  });

  it("repairs an invalid policy with an explicit restricted rule", async () => {
    render(<TableRowAccess table={{ ...table, row_policy_valid: false }} />, { wrapper });
    expect(screen.getByRole("alert")).toHaveTextContent("Records are blocked");
    fireEvent.click(screen.getByRole("button", { name: "Save row rules" }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/tables/table/row-policy", { rule: "grants" }),
    );
  });

  it("does not expose policy editing to a row writer", () => {
    render(<TableRowAccess table={{ ...table, can_edit: false, can_manage_row_access: false }} />, {
      wrapper,
    });
    expect(screen.queryByRole("button", { name: "Save row rules" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("requires live people fields for both assignee permissions before saving", async () => {
    const column: ColumnDef = {
      id: "readers",
      label: "Readers",
      type: "user",
      nullable: true,
      default: null,
      options: [],
      archived: false,
    };
    const user = userEvent.setup();
    render(
      <TableRowAccess
        table={{
          ...table,
          columns: [
            column,
            { ...column, id: "writers", label: "Writers", type: "multi_user" },
            { ...column, id: "archived", label: "Archived people", archived: true },
            { ...column, id: "title", label: "Title", type: "text" },
          ],
        }}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("combobox", { name: "Default row access" }));
    await user.click(await screen.findByRole("option", { name: "People named in row fields" }));
    const save = screen.getByRole("button", { name: "Save row rules" });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("combobox", { name: "Read field" }));
    expect(screen.queryByRole("option", { name: "Archived people" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Title" })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("option", { name: "Readers" }));
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("combobox", { name: "Write field" }));
    await user.click(await screen.findByRole("option", { name: "Writers" }));
    await user.click(save);
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/tables/table/row-policy", {
        rule: "assignee",
        view_column_id: "readers",
        edit_column_id: "writers",
      }),
    );
  });

  it("preserves project membership selectors while saving existing assignee fields", async () => {
    const policy: RowPolicy = {
      rule: "assignee",
      view_column_id: "readers",
      edit_column_id: "writers",
      view_project_link_column_id: "projects",
      view_projects_table_id: "projects-table",
      view_project_members_column_id: "members",
    };
    render(<TableRowAccess table={{ ...table, row_policy: policy }} />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: "Save row rules" }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/tables/table/row-policy", policy),
    );
  });

  it("reports a refused policy change and keeps the form available for retry", async () => {
    vi.mocked(apiClient.put).mockRejectedValue(new Error("Sharing permission was revoked"));
    render(<TableRowAccess table={table} />, { wrapper });
    const save = screen.getByRole("button", { name: "Save row rules" });
    fireEvent.click(save);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Sharing permission was revoked"));
    expect(toast.success).not.toHaveBeenCalled();
    expect(save).toBeEnabled();
    expect(apiClient.put).toHaveBeenCalledWith("/tables/table/row-policy", { rule: "none" });
  });

  it.each([
    ["none", "Everyone with table access"],
    ["grants", "Only people with row grants"],
    ["assignee", "People named in row fields"],
  ] as const)("describes the %s policy without exposing its editor", (rule, label) => {
    render(
      <TableRowAccess table={{ ...table, can_manage_row_access: false, row_policy: { rule } }} />,
      { wrapper },
    );
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("shows an invalid policy as blocked to a person who cannot repair it", () => {
    render(
      <TableRowAccess
        table={{ ...table, can_manage_row_access: false, row_policy_valid: false }}
      />,
      { wrapper },
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Records are blocked");
    expect(screen.queryByText("Everyone with table access")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save row rules" })).not.toBeInTheDocument();
  });
});
