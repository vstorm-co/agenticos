import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps, ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecordDetailSheet } from "./record-detail-sheet";
import { apiClient, ApiError } from "@/lib/api-client";
import { useTableViewStore } from "@/stores";
import type { ColumnDef, RecordRead } from "@/types/tables";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { patch: vi.fn(), get: vi.fn() } };
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
  useTableViewStore.getState().reset();
});

describe("RecordDetailSheet", () => {
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

  it("a reload that finds the record deleted drops the edit and closes the sheet", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "Record not found"));
    const onOpenChange = vi.fn();
    renderSheet({ onOpenChange });
    await raiseConflict();

    await userEvent.click(screen.getByRole("button", { name: /reload and reapply/i }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toast.error).toHaveBeenCalledWith("Record not found");
    expect(useTableViewStore.getState().conflicts).toEqual({});
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

    it("closes from the overlay", () => {
      const onOpenChange = vi.fn();
      const { container } = renderSheet({ onOpenChange });

      fireEvent.click(container.ownerDocument.querySelector("[aria-hidden='true']") as Element);

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
