import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecordDetailSheet } from "./record-detail-sheet";
import { apiClient, ApiError } from "@/lib/api-client";
import { useTableViewStore } from "@/stores";
import type { ColumnDef, RecordRead } from "@/types/tables";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { patch: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const columns: ColumnDef[] = [
  {
    id: "c1",
    label: "Name",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
  },
  {
    id: "c2",
    label: "Retired field",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: true,
  },
];

const record: RecordRead = {
  id: "r1",
  table_id: "t1",
  external_id: null,
  schema_version: 1,
  values: { c1: "Ada" },
  revision: 1,
  created_at: "2026-09-23T00:00:00Z",
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  useTableViewStore.getState().reset();
});

describe("RecordDetailSheet", () => {
  it("renders nothing in the body when there is no record", () => {
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={null}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.queryByText("Name")).not.toBeInTheDocument();
  });

  it("renders one editor per live column and skips an archived one", () => {
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.queryByText("Retired field")).not.toBeInTheDocument();
  });

  it("commits a field edit against the record's own revision", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "r1", revision: 2 });
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
      />,
      { wrapper },
    );

    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "x" } });

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 1,
        values: { c1: "x" },
      }),
    );
  });

  it("shows an empty control when the record holds no value for a column", () => {
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={{ ...record, values: {} }}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("disables every field when the caller may not edit", () => {
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit={false}
        onRefetchRecord={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("shows a conflict banner scoped to the field, keeping the typed value", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
      />,
      { wrapper },
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });

    expect(await screen.findByText(/someone else changed this field/i)).toBeInTheDocument();
    // The typed value stays visible - it is the store's pending value, not the stale server one.
    expect(screen.getByRole("textbox")).toHaveValue("x");
  });

  it("discarding a conflict clears the banner and reverts to the server value", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    await screen.findByText(/someone else changed this field/i);

    await userEvent.click(screen.getByRole("button", { name: /discard/i }));

    expect(screen.queryByText(/someone else changed this field/i)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Ada");
  });

  it("reload-and-reapply refetches the record and commits against its fresh revision", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    const fresh: RecordRead = { ...record, revision: 5, values: { c1: "Ada" } };
    const onRefetchRecord = vi.fn().mockResolvedValue(fresh);
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={onRefetchRecord}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    await screen.findByText(/someone else changed this field/i);

    vi.mocked(apiClient.patch).mockResolvedValueOnce({ id: "r1", revision: 6 });
    await userEvent.click(screen.getByRole("button", { name: /reload and reapply/i }));

    expect(onRefetchRecord).toHaveBeenCalled();
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 5,
        values: { c1: "x" },
      }),
    );
  });

  it("reload-and-reapply does nothing further when the refetch finds no record", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    const onRefetchRecord = vi.fn().mockResolvedValue(undefined);
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={onRefetchRecord}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    await screen.findByText(/someone else changed this field/i);

    vi.mocked(apiClient.patch).mockClear();
    await userEvent.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() => expect(onRefetchRecord).toHaveBeenCalled());
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("a non-conflict edit failure sets no banner", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(new ApiError(422, "invalid"));
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
      />,
      { wrapper },
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(screen.queryByText(/someone else changed this field/i)).not.toBeInTheDocument();
  });
});
