import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
import { saveBlob } from "@/lib/file-access";
import { IMPORT_COLUMNS } from "./import-columns";
import { ImportCasesDialog } from "./import-cases-dialog";

describe("ImportCasesDialog", () => {
  beforeEach(() => vi.clearAllMocks());
  it("downloads JSONL when selected and only opens the file picker on request", async () => {
    const choose = vi.fn();
    const close = vi.fn();
    render(<ImportCasesDialog open onOpenChange={close} onChoose={choose} />);
    await userEvent.click(screen.getByRole("button", { name: "JSONL" }));
    await userEvent.click(screen.getByRole("button", { name: "Download a template" }));
    expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "dataset-template.jsonl");
    expect(choose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Choose file" }));
    expect(close).toHaveBeenCalledWith(false);
    expect(choose).toHaveBeenCalledOnce();
  });
  it("describes every column and downloads a template without opening the picker", async () => {
    const onChoose = vi.fn();
    render(<ImportCasesDialog open onOpenChange={vi.fn()} onChoose={onChoose} />);

    for (const column of IMPORT_COLUMNS) expect(screen.getByText(column)).toBeInTheDocument();
    expect(screen.getByText(/CSV or JSONL file of up to 10 MB/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Download a template" }));
    expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), "dataset-template.csv");
    expect(onChoose).not.toHaveBeenCalled();
  });
});
