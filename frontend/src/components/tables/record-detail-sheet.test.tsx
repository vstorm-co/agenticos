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
        onRecordUpdated={vi.fn()}
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
        onRecordUpdated={vi.fn()}
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
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );

    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "x" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 1,
        values: { c1: "x" },
      }),
    );
  });

  it("reports the server's updated record after a successful commit", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ ...record, values: { c1: "x" }, revision: 2 });
    const onRecordUpdated = vi.fn();
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
        onRecordUpdated={onRecordUpdated}
      />,
      { wrapper },
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));

    await waitFor(() =>
      expect(onRecordUpdated).toHaveBeenCalledWith({ ...record, values: { c1: "x" }, revision: 2 }),
    );
  });

  it("commits a second edit against the revision from the first commit's response, not the sheet's original prop", async () => {
    // The regression this guards: a second field write (or a second write to
    // the same field) used to always resubmit `record.revision` from the
    // props this sheet first opened with, so every edit after the first
    // successful one 409'd forever. The caller (the page) is expected to feed
    // `onRecordUpdated`'s value back in as a new `record` prop - simulated
    // here with `rerender` - and this proves the *next* commit picks it up.
    vi.mocked(apiClient.patch).mockResolvedValueOnce({
      ...record,
      values: { c1: "x" },
      revision: 2,
    });
    const { rerender } = render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 1,
        values: { c1: "x" },
      }),
    );

    rerender(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={{ ...record, values: { c1: "x" }, revision: 2 }}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
        onRecordUpdated={vi.fn()}
      />,
    );
    vi.mocked(apiClient.patch).mockResolvedValueOnce({
      ...record,
      values: { c1: "xy" },
      revision: 3,
    });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "xy" } });
    fireEvent.blur(screen.getByRole("textbox"));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 2,
        values: { c1: "xy" },
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
        onRecordUpdated={vi.fn()}
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
        onRecordUpdated={vi.fn()}
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
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));

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
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));
    await screen.findByText(/someone else changed this field/i);

    await userEvent.click(screen.getByRole("button", { name: /discard/i }));

    expect(screen.queryByText(/someone else changed this field/i)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Ada");
  });

  it("discard refetches the record, rather than only clearing the local banner", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    const onRefetchRecord = vi.fn().mockResolvedValue(record);
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={onRefetchRecord}
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));
    await screen.findByText(/someone else changed this field/i);

    await userEvent.click(screen.getByRole("button", { name: /discard/i }));

    await waitFor(() => expect(onRefetchRecord).toHaveBeenCalled());
  });

  it("a failed reload does not clear the pending edit - there would be no way back to it", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(
      new ApiError(409, "stale", {
        error: { code: "REVISION_CONFLICT", message: "stale", details: null },
      }),
    );
    const onRefetchRecord = vi.fn().mockRejectedValue(new Error("network down"));
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={columns}
        record={record}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={onRefetchRecord}
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));
    await screen.findByText(/someone else changed this field/i);

    await userEvent
      .click(screen.getByRole("button", { name: /reload and reapply/i }))
      .catch(() => {});

    await waitFor(() => expect(onRefetchRecord).toHaveBeenCalled());
    // Still conflicted, with the typed value intact - the failed refetch
    // never got the chance to drop it.
    expect(screen.getByText(/someone else changed this field/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("x");
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
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));
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

  it("keeps the conflict banner when the retry commit itself fails, not only when the refetch does", async () => {
    // The refetch (GET) succeeding is not the same as the retry write (PATCH)
    // succeeding. Clearing the banner as soon as the refetch lands would drop
    // the pending edit for good the moment the retry PATCH itself then fails -
    // this pins that the banner (and the typed value) survive that case too.
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
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));
    await screen.findByText(/someone else changed this field/i);

    vi.mocked(apiClient.patch).mockRejectedValueOnce(new Error("network down"));
    await userEvent.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenLastCalledWith("/tables/t1/records/r1", {
        expected_revision: 5,
        values: { c1: "x" },
      }),
    );
    expect(screen.getByText(/someone else changed this field/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("x");
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
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));
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
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(screen.queryByText(/someone else changed this field/i)).not.toBeInTheDocument();
  });

  it("keeps a field's conflict banner and typed value when a different field of the same record commits successfully", async () => {
    // The regression this guards: the conflict store used to key by record id
    // alone, so a second field's *successful* write cleared the whole record's
    // one conflict entry - silently dropping the first field's still-pending
    // banner and the value the user had typed into it, even though the two
    // fields were never racing each other.
    const twoLiveColumns: ColumnDef[] = [
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
        id: "c3",
        label: "Email",
        type: "text",
        nullable: true,
        default: null,
        options: [],
        archived: false,
      },
    ];
    const twoFieldRecord: RecordRead = { ...record, values: { c1: "Ada", c3: "ada@example.com" } };
    vi.mocked(apiClient.patch)
      .mockRejectedValueOnce(
        new ApiError(409, "stale", {
          error: { code: "REVISION_CONFLICT", message: "stale", details: null },
        }),
      )
      .mockResolvedValueOnce({
        ...twoFieldRecord,
        values: { c1: "Ada", c3: "grace@example.com" },
        revision: 2,
      });
    render(
      <RecordDetailSheet
        tableId="t1"
        columns={twoLiveColumns}
        record={twoFieldRecord}
        open
        onOpenChange={vi.fn()}
        canEdit
        onRefetchRecord={vi.fn()}
        onRecordUpdated={vi.fn()}
      />,
      { wrapper },
    );
    const [nameInput, emailInput] = screen.getAllByRole("textbox");

    fireEvent.change(nameInput as HTMLElement, { target: { value: "Grace" } });
    fireEvent.blur(nameInput as HTMLElement);
    await screen.findByText(/someone else changed this field/i);

    fireEvent.change(emailInput as HTMLElement, { target: { value: "grace@example.com" } });
    fireEvent.blur(emailInput as HTMLElement);

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/someone else changed this field/i)).toBeInTheDocument();
    expect(nameInput).toHaveValue("Grace");
  });
});
