import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ComponentProps, type ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecordDetailSheet } from "./record-detail-sheet";
import { apiClient, ApiError } from "@/lib/api-client";
import { useTableViewStore } from "@/stores";
import type { ColumnDef, RecordRead } from "@/types/tables";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { patch: vi.fn(), get: vi.fn(), delete: vi.fn() } };
});
const deleteLater = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-deferred-delete", () => ({ useDeferredDelete: () => deleteLater }));
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

const conflict409 = () =>
  new ApiError(409, "stale", {
    error: { code: "REVISION_CONFLICT", message: "stale", details: null },
  });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type SheetProps = ComponentProps<typeof RecordDetailSheet>;

function sheet(overrides: Partial<SheetProps> = {}) {
  const props: SheetProps = {
    tableId: "t1",
    columns,
    record,
    open: true,
    onOpenChange: vi.fn(),
    canEdit: true,
    onRecordUpdated: vi.fn(),
    ...overrides,
  };
  return <RecordDetailSheet {...props} />;
}

function renderSheet(overrides: Partial<SheetProps> = {}) {
  return render(sheet(overrides), { wrapper });
}

async function raiseConflict(value = "x") {
  vi.mocked(apiClient.patch).mockRejectedValueOnce(conflict409());
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
  await screen.findByText(/someone else changed this field/i);
}

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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockReset().mockResolvedValue(record);
  useTableViewStore.getState().reset();
});

describe("RecordDetailSheet", () => {
  it("is titled by its first column, and says when it was added and changed", () => {
    const { rerender } = renderSheet({
      record: { ...record, updated_at: "2026-09-24T10:00:00Z" },
    });
    expect(screen.getByRole("heading", { name: "Ada" })).toBeTruthy();
    for (const label of ["Created", "Last updated", "Created by", "Updated by"])
      expect(screen.getByText(label, { exact: true })).toBeVisible();
    expect(screen.getByText("Created", { exact: true }).nextElementSibling?.textContent).not.toBe(
      screen.getByText("Last updated", { exact: true }).nextElementSibling?.textContent,
    );

    // Nothing in the first column, and never changed: the plain title, only its adding.
    rerender(sheet({ record: { ...record, values: {} } }));
    expect(screen.getByRole("heading", { name: "Record" })).toBeTruthy();
    expect(screen.getByText("Created", { exact: true }).nextElementSibling?.textContent).toBe(
      screen.getByText("Last updated", { exact: true }).nextElementSibling?.textContent,
    );

    // A yes/no first column is titled by how it reads.
    const done: ColumnDef = { ...columns[0]!, id: "b1", label: "Done", type: "boolean" };
    rerender(sheet({ columns: [done], record: { ...record, values: { b1: true } } }));
    expect(screen.getByRole("heading", { name: "True" })).toBeTruthy();
    rerender(sheet({ columns: [done], record: { ...record, values: { b1: false } } }));
    expect(screen.getByRole("heading", { name: "False" })).toBeTruthy();
  });

  it("renders nothing in the body when there is no record", () => {
    renderSheet({ record: null });
    expect(screen.queryByText("Name")).not.toBeInTheDocument();
  });

  it("renders one editor per live column and skips an archived one", () => {
    renderSheet();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.queryByText("Retired field")).not.toBeInTheDocument();
  });

  it("commits a field edit against the record's own revision", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "r1", revision: 2 });
    renderSheet();

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
    renderSheet({ onRecordUpdated });

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));

    await waitFor(() =>
      expect(onRecordUpdated).toHaveBeenCalledWith({ ...record, values: { c1: "x" }, revision: 2 }),
    );
  });

  it("commits a second edit against the revision from the first commit's response, not the sheet's original prop", async () => {
    // A second field write (or a second write to the same field) used to
    // resubmit the revision this sheet opened with, so every edit after the
    // first successful one 409'd.
    vi.mocked(apiClient.patch).mockResolvedValueOnce({
      ...record,
      values: { c1: "x" },
      revision: 2,
    });
    const { rerender } = renderSheet();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 1,
        values: { c1: "x" },
      }),
    );

    rerender(sheet({ record: { ...record, values: { c1: "x" }, revision: 2 } }));
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

  describe("two commits to one record started within one round trip", () => {
    // Field A commits on blur and field B commits while A's write is still in
    // flight - the blur caused by clicking B is exactly that. Both used to
    // carry the revision the sheet held, and the first write's callbacks were
    // dropped by the one shared mutation observer, so a refused A showed no
    // banner and a landed A never advanced the sheet's revision.
    async function startBoth() {
      const first = deferred<RecordRead>();
      const second = deferred<RecordRead>();
      vi.mocked(apiClient.patch)
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise);
      const onRecordUpdated = vi.fn();
      renderSheet({ columns: twoLiveColumns, record: twoFieldRecord, onRecordUpdated });
      const [nameInput, emailInput] = screen.getAllByRole("textbox") as HTMLElement[];
      fireEvent.change(nameInput!, { target: { value: "Grace" } });
      fireEvent.blur(nameInput!);
      fireEvent.change(emailInput!, { target: { value: "grace@example.com" } });
      fireEvent.blur(emailInput!);
      await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
      return { first, second, onRecordUpdated, nameInput: nameInput! };
    }

    it("sends the second only after the first settles, against the first's new revision", async () => {
      const { first, second, onRecordUpdated } = await startBoth();

      first.resolve({
        ...twoFieldRecord,
        values: { c1: "Grace", c3: "ada@example.com" },
        revision: 2,
      });
      await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
      expect(apiClient.patch).toHaveBeenLastCalledWith("/tables/t1/records/r1", {
        expected_revision: 2,
        values: { c3: "grace@example.com" },
      });
      second.resolve({ ...twoFieldRecord, revision: 3 });

      await waitFor(() => expect(onRecordUpdated).toHaveBeenCalledTimes(2));
      expect(onRecordUpdated.mock.calls.map(([updated]) => updated.revision)).toEqual([2, 3]);
      expect(screen.queryByText(/someone else changed this field/i)).not.toBeInTheDocument();
    });

    it("keeps the first's banner and typed value when the first is refused", async () => {
      const { first, second, nameInput } = await startBoth();

      first.reject(conflict409());
      expect(await screen.findByText(/someone else changed this field/i)).toBeInTheDocument();
      expect(nameInput).toHaveValue("Grace");
      await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
      second.resolve({ ...twoFieldRecord, revision: 2 });

      await waitFor(() =>
        expect(screen.getAllByText(/someone else changed this field/i)).toHaveLength(1),
      );
      expect(nameInput).toHaveValue("Grace");
    });
  });

  it("shows an empty control when the record holds no value for a column", () => {
    renderSheet({ record: { ...record, values: {} } });
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("disables every field when the caller may not edit", () => {
    renderSheet({ canEdit: false });
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("shows a conflict banner scoped to the field, keeping the typed value", async () => {
    renderSheet();
    await raiseConflict();
    // The typed value stays visible - it is the store's pending value, not the stale server one.
    expect(screen.getByRole("textbox")).toHaveValue("x");
  });

  it("discarding a conflict clears the banner and shows the refetched server value", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ ...record, values: { c1: "Ada" }, revision: 4 });
    const onRecordUpdated = vi.fn();
    renderSheet({ onRecordUpdated });
    await raiseConflict();

    await userEvent.click(screen.getByRole("button", { name: /discard/i }));

    expect(screen.queryByText(/someone else changed this field/i)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Ada");
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/records/r1"));
    expect(onRecordUpdated).toHaveBeenCalledWith({ ...record, values: { c1: "Ada" }, revision: 4 });
  });

  it("says so when the refetch behind a discard fails", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(500, "down"));
    renderSheet();
    await raiseConflict();

    await userEvent.click(screen.getByRole("button", { name: /discard/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("down"));
  });

  it("a failed reload keeps the pending edit and says why", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(503, "network down"));
    const onOpenChange = vi.fn();
    renderSheet({ onOpenChange });
    await raiseConflict();

    await userEvent.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("network down"));
    // Still conflicted, with the typed value intact.
    expect(screen.getByText(/someone else changed this field/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("x");
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("drops a pending edit when the record is deleted before explicit reload", async () => {
    const onOpenChange = vi.fn();
    renderSheet({ onOpenChange });
    await raiseConflict();
    await screen.findByTestId("conflict-now");
    vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError(404, "Record not found"));

    await userEvent.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toast.error).toHaveBeenCalledWith("Record not found");
    expect(useTableViewStore.getState().conflicts).toEqual({});
    expect(apiClient.patch).toHaveBeenCalledTimes(1);
  });

  it("a conflict on a record since deleted drops the edit and closes the sheet", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "Record not found"));
    const onOpenChange = vi.fn();
    renderSheet({ onOpenChange });
    await raiseConflict();

    // The record is read again as soon as the conflict shows, and is gone.
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toast.error).toHaveBeenCalledWith("Record not found");
    expect(useTableViewStore.getState().conflicts).toEqual({});
  });

  it("says what the field holds now, who changed it and when, and refreshes the record", async () => {
    const theirs: RecordRead = {
      ...record,
      values: { c1: "Grace" },
      revision: 3,
      updated_at: "2026-11-13T10:28:00Z",
      updated_source: { kind: "user", id: "u2", name: "Ola Nowak" },
    };
    vi.mocked(apiClient.get).mockResolvedValue(theirs);
    const onRecordUpdated = vi.fn();
    renderSheet({ onRecordUpdated });
    await raiseConflict("Ada Lovelace");

    const now = await screen.findByTestId("conflict-now");
    expect(now).toHaveTextContent(/^Now: Grace, changed by .*Ola Nowak at .+\./);
    expect(now).toHaveTextContent("Your value is in the field.");
    expect(onRecordUpdated).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Grace" })).toBeVisible();
    expect(screen.getByRole("textbox")).toHaveValue("Ada Lovelace");
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("forgets what a cleared conflict read, so the next one shows only its own", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      ...record,
      values: { c1: "First" },
      revision: 2,
    });
    renderSheet();
    await raiseConflict("x");
    expect(await screen.findByTestId("conflict-now")).toHaveTextContent("Now: First");

    act(() => useTableViewStore.getState().clearConflict("r1", "c1"));
    await waitFor(() => expect(screen.queryByTestId("conflict-now")).toBeNull());

    const second = deferred<RecordRead>();
    vi.mocked(apiClient.get).mockReturnValueOnce(second.promise);
    await raiseConflict("y");
    // Until its own read lands, the second conflict says nothing of the first's value.
    expect(screen.queryByTestId("conflict-now")).toBeNull();
    second.resolve({ ...record, values: { c1: "Second" }, revision: 3 });
    expect(await screen.findByTestId("conflict-now")).toHaveTextContent("Now: Second");
  });

  it("reads the record again for a conflict raised before the sheet opened", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ ...record, values: { c1: "" }, revision: 2 });
    useTableViewStore
      .getState()
      .setConflict({ recordId: "r1", pendingValues: { c1: "Mine" }, fieldId: "c1" });
    const view = renderSheet({ open: false });
    expect(apiClient.get).not.toHaveBeenCalled();

    view.rerender(sheet({ open: true }));

    expect(await screen.findByTestId("conflict-now")).toHaveTextContent(
      "Now: empty, changed by someone else.",
    );
  });

  it("reload-and-reapply refetches the record and commits against its fresh revision", async () => {
    const fresh: RecordRead = { ...record, revision: 5, values: { c1: "Ada" } };
    vi.mocked(apiClient.get).mockResolvedValue(fresh);
    renderSheet();
    await raiseConflict();

    vi.mocked(apiClient.patch).mockResolvedValueOnce({ ...record, revision: 6 });
    await userEvent.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
        expected_revision: 5,
        values: { c1: "x" },
      }),
    );
    await waitFor(() =>
      expect(screen.queryByText(/someone else changed this field/i)).not.toBeInTheDocument(),
    );
  });

  it("keeps the conflict banner when the retry commit itself fails, not only when the refetch does", async () => {
    // The refetch succeeding is not the retry write succeeding: the banner (and
    // the typed value) survive a retry PATCH that fails.
    vi.mocked(apiClient.get).mockResolvedValue({ ...record, revision: 5, values: { c1: "Ada" } });
    renderSheet();
    await raiseConflict();

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

  it("a non-conflict edit failure sets no banner", async () => {
    vi.mocked(apiClient.patch).mockRejectedValueOnce(new ApiError(422, "invalid"));
    renderSheet();

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.blur(screen.getByRole("textbox"));

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(screen.queryByText(/someone else changed this field/i)).not.toBeInTheDocument();
  });

  it("keeps a field's conflict banner and typed value when a different field of the same record commits successfully", async () => {
    // Keyed by record alone, the second field's successful write used to clear
    // the first field's still-pending banner and typed value.
    vi.mocked(apiClient.patch)
      .mockRejectedValueOnce(conflict409())
      .mockResolvedValueOnce({
        ...twoFieldRecord,
        values: { c1: "Ada", c3: "grace@example.com" },
        revision: 2,
      });
    renderSheet({ columns: twoLiveColumns, record: twoFieldRecord });
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

  describe("deleting", () => {
    const confirm = () =>
      screen.getAllByRole("button", { name: "Delete record" }).at(-1) as HTMLElement;

    it("deletes the record against its revision and closes the sheet", async () => {
      vi.mocked(apiClient.delete).mockResolvedValueOnce(undefined);
      const onOpenChange = vi.fn();
      renderSheet({ onOpenChange });

      fireEvent.click(screen.getByRole("button", { name: "Delete record" }));
      expect(screen.getByText("Delete this record?")).toBeInTheDocument();
      // Escape belongs to the confirmation now: it closes that, not the sheet.
      fireEvent.keyDown(document, { key: "Escape" });
      await waitFor(() =>
        expect(screen.queryByText("Delete this record?")).not.toBeInTheDocument(),
      );
      expect(onOpenChange).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "Delete record" }));
      fireEvent.click(confirm());

      await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
      expect(deleteLater).toHaveBeenCalledWith([
        expect.objectContaining({ id: "r1", revision: 1 }),
      ]);
    });

    it("offers no delete to a reader", () => {
      renderSheet({ canEdit: false });
      expect(screen.queryByRole("button", { name: "Delete record" })).not.toBeInTheDocument();
    });
  });

  describe("closing", () => {
    it("moves focus into the sheet, onto its close button", () => {
      renderSheet();
      expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    });

    it("closes from its close button", async () => {
      const onOpenChange = vi.fn();
      renderSheet({ onOpenChange });

      await userEvent.click(screen.getByRole("button", { name: "Close" }));

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it("closes on Escape", () => {
      const onOpenChange = vi.fn();
      renderSheet({ onOpenChange });

      fireEvent.keyDown(document, { key: "Escape" });

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it("closes from the overlay", async () => {
      const onOpenChange = vi.fn();
      const { container } = renderSheet({ onOpenChange });

      await userEvent.click(
        container.ownerDocument.querySelector("[data-state='open'].fixed.inset-0") as Element,
      );

      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it("commits the focused field before Escape closes the sheet", async () => {
      vi.mocked(apiClient.patch).mockResolvedValue({
        ...record,
        values: { c1: "typed" },
        revision: 2,
      });
      const onOpenChange = vi.fn();
      renderSheet({ onOpenChange });
      const input = screen.getByRole("textbox");
      input.focus();
      fireEvent.change(input, { target: { value: "typed" } });

      fireEvent.keyDown(input, { key: "Escape" });

      expect(onOpenChange).toHaveBeenCalledWith(false);
      await waitFor(() =>
        expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
          expected_revision: 1,
          values: { c1: "typed" },
        }),
      );
    });

    it("leaves an Escape a control inside the sheet already handled alone", () => {
      const onOpenChange = vi.fn();
      renderSheet({ onOpenChange });
      const event = new KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      });
      event.preventDefault();

      document.dispatchEvent(event);

      expect(onOpenChange).not.toHaveBeenCalled();
    });

    it("says so when a field committed by closing is refused after the sheet is gone", async () => {
      // The edit is kept for the record's next opening, but with the sheet
      // closed there was no banner to show it - the refusal said nothing.
      const pending = deferred<RecordRead>();
      vi.mocked(apiClient.patch).mockReturnValueOnce(pending.promise);
      const onOpenChange = vi.fn();
      const { rerender } = renderSheet({ onOpenChange });
      const input = screen.getByRole("textbox");
      input.focus();
      fireEvent.change(input, { target: { value: "typed" } });
      fireEvent.keyDown(document, { key: "Escape" });
      rerender(sheet({ onOpenChange, open: false }));

      pending.reject(conflict409());

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Someone else changed that record, so your last edit was not saved. Open the record to reapply or discard it.",
        ),
      );
      expect(useTableViewStore.getState().conflicts.r1?.c1?.pendingValues).toEqual({ c1: "typed" });
    });

    it("does not toast a refusal the open sheet shows as a banner", async () => {
      renderSheet();
      await raiseConflict();
      expect(toast.error).not.toHaveBeenCalled();
    });

    it("gives focus back to what opened it once it closes", async () => {
      const opener = document.createElement("button");
      document.body.appendChild(opener);
      opener.focus();
      const { rerender } = renderSheet();
      expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();

      rerender(sheet({ open: false }));

      await waitFor(() => expect(opener).toHaveFocus());
      opener.remove();
    });

    describe("keeps keyboard focus in the shared sheet", () => {
      it("wraps from the last control to the first and back", async () => {
        renderSheet();
        const close = screen.getByRole("button", { name: "Close" });
        const remove = screen.getByRole("button", { name: "Delete record" });
        remove.focus();
        await userEvent.tab();
        expect(close).toHaveFocus();
        await userEvent.tab({ shift: true });
        expect(remove).toHaveFocus();
      });

      it("cycles through the read-only sheet controls", async () => {
        renderSheet({ canEdit: false });
        const close = screen.getByRole("button", { name: "Close" });
        await userEvent.tab();
        expect(screen.getByRole("button", { name: "Full screen" })).toHaveFocus();
        await userEvent.tab();
        expect(close).toHaveFocus();
      });

      it("brings focus moved behind the overlay back into the sheet", () => {
        const behind = document.createElement("button");
        document.body.appendChild(behind);
        renderSheet();
        behind.focus();
        expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
        behind.remove();
      });

      it("allows a real select popup to take focus and commit its choice", async () => {
        vi.mocked(apiClient.patch).mockResolvedValue({
          ...record,
          values: { c1: "chosen" },
          revision: 2,
        });
        renderSheet({
          columns: [
            {
              ...columns[0]!,
              type: "single_select",
              options: [{ id: "chosen", label: "Chosen", archived: false }],
            },
          ],
        });
        await userEvent.click(screen.getByRole("combobox"));
        await userEvent.click(screen.getByRole("option", { name: "Chosen" }));
        await waitFor(() =>
          expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
            expected_revision: 1,
            values: { c1: "chosen" },
          }),
        );
        expect(screen.getByRole("dialog")).toBeVisible();
      });
    });

    it("ignores other keys, and Escape once closed", () => {
      const onOpenChange = vi.fn();
      renderSheet({ onOpenChange, open: false });
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onOpenChange).not.toHaveBeenCalled();

      cleanupAndRender({ onOpenChange });
      fireEvent.keyDown(document, { key: "Enter" });
      expect(onOpenChange).not.toHaveBeenCalled();
    });
  });
});

function cleanupAndRender(overrides: Partial<SheetProps>) {
  cleanup();
  renderSheet(overrides);
}

it("expands the whole record while preserving the current editor", async () => {
  renderSheet();
  const input = screen.getByRole("textbox", { name: "Name" });
  await userEvent.click(screen.getByRole("button", { name: "Full screen" }));
  expect(screen.getByRole("dialog").className).toContain("sm:w-screen");
  expect(screen.getByRole("textbox", { name: "Name" })).toBe(input);
  await userEvent.click(screen.getByRole("button", { name: "Exit full screen" }));
  expect(screen.getByRole("dialog").className).toContain("sm:w-[44rem]");
});

it("places every property before document bodies, preserving property order", () => {
  const document = { ...columns[0]!, id: "doc", label: "Notes", type: "rich_text" as const };
  const owner = { ...columns[0]!, id: "owner", label: "Owner" };
  const kind = { ...columns[0]!, id: "kind", label: "Kind" };
  renderSheet({ columns: [columns[0]!, document, owner, kind] });
  const fields = screen.getAllByRole("textbox");
  expect(fields.map((input) => input.id)).toEqual([
    "cell-c1",
    "cell-owner",
    "cell-kind",
    "cell-doc",
  ]);
});

it("reads a replacement conflict even while the previous read is pending", async () => {
  const first = deferred<RecordRead>();
  const second = deferred<RecordRead>();
  vi.mocked(apiClient.get).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  renderSheet();
  act(() =>
    useTableViewStore
      .getState()
      .setConflict({ recordId: "r1", fieldId: "c1", pendingValues: { c1: "Mine 1" } }),
  );
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));
  act(() =>
    useTableViewStore
      .getState()
      .setConflict({ recordId: "r1", fieldId: "c1", pendingValues: { c1: "Mine 2" } }),
  );
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  await act(async () => second.resolve({ ...record, revision: 3, values: { c1: "Newest" } }));
  expect(screen.getByTestId("conflict-now")).toHaveTextContent("Now: Newest");
  await act(async () => first.resolve({ ...record, revision: 2, values: { c1: "Older" } }));
  expect(screen.getByTestId("conflict-now")).toHaveTextContent("Now: Newest");
  expect(screen.getByRole("textbox")).toHaveValue("Mine 2");
});

it("does not let a deleted record's late read close the next record", async () => {
  const pending = deferred<RecordRead>();
  vi.mocked(apiClient.get).mockReturnValueOnce(pending.promise);
  const onOpenChange = vi.fn();
  const view = renderSheet({ onOpenChange });
  await raiseConflict();
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));
  view.rerender(
    sheet({ record: { ...record, id: "r2", values: { c1: "Next record" } }, onOpenChange }),
  );
  await act(async () => pending.reject(new ApiError(404, "Record not found")));
  expect(onOpenChange).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox")).toHaveValue("Next record");
});

it("preserves an unsubmitted neighbouring draft and its original revision", async () => {
  const pending = deferred<RecordRead>();
  vi.mocked(apiClient.patch)
    .mockReturnValueOnce(pending.promise)
    .mockRejectedValueOnce(conflict409());
  vi.mocked(apiClient.get).mockResolvedValue({
    ...twoFieldRecord,
    revision: 3,
    values: { c1: "Theirs", c3: "theirs@example.com" },
  });
  function EditingSheet() {
    const [current, setCurrent] = useState(twoFieldRecord);
    return sheet({ columns: twoLiveColumns, record: current, onRecordUpdated: setCurrent });
  }
  render(<EditingSheet />, { wrapper });
  const name = screen.getByLabelText("Name");
  const email = screen.getByLabelText("Email");
  fireEvent.change(name, { target: { value: "My name" } });
  fireEvent.blur(name);
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
  fireEvent.change(email, { target: { value: "mine@example.com" } });
  await act(async () => pending.reject(conflict409()));
  await screen.findByTestId("conflict-now");
  expect(email).toHaveValue("mine@example.com");
  fireEvent.blur(email);
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
  expect(apiClient.patch).toHaveBeenLastCalledWith("/tables/t1/records/r1", {
    expected_revision: 1,
    values: { c3: "mine@example.com" },
  });
});

it("bounds a long conflict preview while retaining the refused edit", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({
    ...record,
    revision: 2,
    values: { c1: "x".repeat(100000) },
  });
  renderSheet({ columns: [{ ...twoLiveColumns[0]!, type: "long_text" }] });
  await raiseConflict("My edit");
  const preview = await screen.findByTestId("conflict-now");
  expect(preview.textContent!.length).toBeLessThan(500);
  expect(preview).toHaveTextContent("…");
  expect(screen.getByRole("textbox")).toHaveValue("My edit");
  expect(screen.getByRole("button", { name: /reload and reapply/i })).toBeVisible();
});
