import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { DatasetFileActions, refusedRows } from "./dataset-file-actions";

const exportDataset = vi.fn();
vi.mock("@/hooks/use-datasets", () => ({
  exportDataset: (...args: unknown[]) => exportDataset(...args),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

describe("DatasetFileActions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("exports the version on screen in either format", async () => {
    exportDataset.mockResolvedValue(undefined);
    render(<DatasetFileActions datasetId="d1" version={2} />);
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await userEvent.click(screen.getByRole("button", { name: "Export JSONL" }));
    expect(exportDataset.mock.calls).toEqual([
      ["d1", { format: "csv", version: 2 }],
      ["d1", { format: "jsonl", version: 2 }],
    ]);
    expect(screen.queryByRole("button", { name: "Import" })).toBeNull();
  });

  it("says when an export fails", async () => {
    exportDataset.mockRejectedValue(new Error("boom"));
    render(<DatasetFileActions datasetId="d1" version={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("imports the chosen file, and says why one was refused", async () => {
    const onImport = vi.fn().mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("row 3"));
    render(<DatasetFileActions datasetId="d1" version={null} onImport={onImport} />);
    const picker = screen.getByLabelText("Choose a CSV or JSONL file to import");
    const click = vi.spyOn(picker, "click");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(click).toHaveBeenCalled();

    const file = new File(["input\nq\n"], "cases.csv", { type: "text/csv" });
    await userEvent.upload(picker, file);
    expect(onImport).toHaveBeenCalledWith(file);
    await userEvent.upload(picker, file);
    await waitFor(() => expect(toast.error).toHaveBeenCalled());

    fireEvent.change(picker, { target: { files: [] } });
    fireEvent.change(picker, { target: { files: null } });
    expect(onImport).toHaveBeenCalledTimes(2);
  });
});

describe("refusedRows", () => {
  const t = (key: string, values: Record<string, string | number>) =>
    `${key}|${Object.values(values).join("|")}`;

  it("names each refused row and field, at most five of them", () => {
    const fields = [
      { field: "rows.2.order_mode", message: "Input should be any" },
      { field: "rows.4", message: "Not a JSON object" },
      { field: "file", message: "ignored" },
      ...[5, 6, 7, 8].map((row) => ({ field: `rows.${row}`, message: "x" })),
    ];
    const refusal = new ApiError(400, "2 rows could not be imported", {
      error: { code: "BAD_REQUEST", message: "refused", details: { fields } },
    });
    expect(refusedRows(refusal, t)?.split("\n")).toEqual([
      "importRowFieldProblem|2|order_mode|Input should be any",
      "importRowProblem|4|Not a JSON object",
      "importRowProblem|5|x",
      "importRowProblem|6|x",
      "importRowProblem|7|x",
    ]);
  });

  it("adds nothing when the refusal names no row", () => {
    expect(refusedRows(new Error("down"), t)).toBeUndefined();
  });
});
