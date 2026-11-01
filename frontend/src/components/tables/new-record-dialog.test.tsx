import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewRecordDialog, isRequired } from "./new-record-dialog";
import { apiClient, ApiError } from "@/lib/api-client";
import type { ColumnDef } from "@/types/tables";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { post: vi.fn() } };
});
/** The options a routine confirmation goes out with (`toastDone`). */
const routine = expect.objectContaining({ position: "bottom-center" });

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const base: Omit<ColumnDef, "id" | "label" | "type"> = {
  nullable: true,
  default: null,
  options: [],
  archived: false,
};

const columns: ColumnDef[] = [
  { ...base, id: "name", label: "Name", type: "text", nullable: false },
  { ...base, id: "seats", label: "Seats", type: "integer" },
  { ...base, id: "paid", label: "Paid", type: "boolean", nullable: false },
  { ...base, id: "tier", label: "Tier", type: "text", nullable: false, default: "free" },
  { ...base, id: "old", label: "Retired", type: "text", archived: true },
];

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderDialog(onOpenChange = vi.fn()) {
  render(<NewRecordDialog tableId="t1" columns={columns} open onOpenChange={onOpenChange} />, {
    wrapper,
  });
  return onOpenChange;
}

beforeEach(() => vi.clearAllMocks());

describe("isRequired", () => {
  it("is a column that can be neither empty nor defaulted", () => {
    expect(columns.map(isRequired)).toEqual([true, false, true, false, false]);
  });
});

describe("NewRecordDialog", () => {
  it("shows the document template immediately and allows an explicitly blank body", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "r1" });
    render(
      <NewRecordDialog
        tableId="t1"
        columns={[
          { ...base, id: "body", label: "Document", type: "rich_text", default: "# Default note" },
        ]}
        open
        onOpenChange={vi.fn()}
      />,
      { wrapper },
    );
    const input = screen.getByRole("textbox", { name: "Document" });
    expect(input).toHaveValue("# Default note");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);
    fireEvent.click(screen.getByRole("button", { name: "Add record" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(expect.anything(), { values: { body: "" } }),
    );
  });

  it("starts from a value typed on the grid's new-record line", () => {
    render(
      <NewRecordDialog
        tableId="t1"
        columns={columns}
        open
        onOpenChange={vi.fn()}
        initial={{ name: "Ada" }}
      />,
      { wrapper },
    );
    expect(screen.getByLabelText(/^Name/)).toHaveValue("Ada");
  });

  it("asks for every live column and marks the required ones", () => {
    renderDialog();

    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Seats")).toBeInTheDocument();
    expect(screen.queryByText("Retired")).not.toBeInTheDocument();
    expect(screen.getAllByText("*")).toHaveLength(2);
  });

  it("refuses to write until a required column has a value", () => {
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Add record" }));

    expect(screen.getByText("This column needs a value.")).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("writes what was filled in, a switch at no, and leaves the rest to defaults", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "r1" });
    const onOpenChange = renderDialog();

    const [name] = screen.getAllByRole("textbox");
    fireEvent.change(name as HTMLElement, { target: { value: "Acme" } });
    fireEvent.blur(name as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "Add record" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/records", {
        values: { name: "Acme", paid: false },
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("Record added.", routine);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps what was typed when the write is refused", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new ApiError(422, "no", null));
    const onOpenChange = renderDialog();

    const [name] = screen.getAllByRole("textbox");
    fireEvent.change(name as HTMLElement, { target: { value: "Acme" } });
    fireEvent.blur(name as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "Add record" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getAllByRole("textbox")[0]).toHaveValue("Acme");
  });

  it("forgets the form when cancelled", () => {
    const onOpenChange = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("passes an opening change straight through", () => {
    const onOpenChange = vi.fn();
    render(
      <NewRecordDialog tableId="t1" columns={columns} open={false} onOpenChange={onOpenChange} />,
      { wrapper },
    );
    expect(screen.queryByText("New record")).not.toBeInTheDocument();
  });
});
