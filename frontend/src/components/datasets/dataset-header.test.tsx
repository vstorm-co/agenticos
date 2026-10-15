import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Dataset } from "@/types/datasets";
import { DatasetHeader } from "./dataset-header";

const exportDataset = vi.fn();
vi.mock("@/hooks/use-datasets", () => ({
  exportDataset: (...args: unknown[]) => exportDataset(...args),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

function dataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    id: "d1",
    name: "Refunds",
    description: null,
    visibility: "org",
    owner_user_id: null,
    latest_version: 2,
    case_count: 3,
    can_edit: true,
    created_at: "2026-10-01T00:00:00Z",
    ...overrides,
  } as Dataset;
}

const handlers = () => ({
  onEditDetails: vi.fn(),
  onShare: vi.fn(),
  onDelete: vi.fn(),
});

async function openMenu() {
  await userEvent.click(screen.getByRole("button", { name: "More actions" }));
}

describe("DatasetHeader", () => {
  beforeEach(() => vi.clearAllMocks());

  it("adds a case from the button and puts every rarer action in the menu", async () => {
    const onAddCase = vi.fn();
    const on = handlers();
    render(
      <DatasetHeader
        dataset={dataset()}
        version={null}
        actions={<button type="button">Run evals</button>}
        onAddCase={onAddCase}
        onImport={vi.fn()}
        {...on}
      />,
    );

    expect(screen.getByRole("button", { name: "Run evals" })).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add case" }));
    expect(onAddCase).toHaveBeenCalled();

    for (const [item, handler] of [
      ["Edit details", on.onEditDetails],
      ["Share", on.onShare],
      ["Delete", on.onDelete],
    ] as const) {
      await openMenu();
      await userEvent.click(await screen.findByRole("menuitem", { name: item }));
      expect(handler).toHaveBeenCalled();
    }
  });

  it("offers a reader sharing and export, and nothing that changes the dataset", async () => {
    render(
      <DatasetHeader
        dataset={dataset({ can_edit: false, latest_version: 0 })}
        version={null}
        {...handlers()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Add case" })).toBeNull();
    expect(screen.queryByText("v0")).toBeNull();
    await openMenu();
    const items = (await screen.findAllByRole("menuitem")).map((item) => item.textContent);
    expect(items).toEqual(["Share", "Export CSV", "Export JSONL"]);
  });

  it("exports the version on screen in either format, and says when one fails", async () => {
    exportDataset.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("boom"));
    render(<DatasetHeader dataset={dataset()} version={2} {...handlers()} />);

    await openMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Export CSV" }));
    await openMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Export JSONL" }));

    expect(exportDataset.mock.calls).toEqual([
      ["d1", { format: "csv", version: 2 }],
      ["d1", { format: "jsonl", version: 2 }],
    ]);
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("has nothing to export while the dataset holds no case", async () => {
    render(<DatasetHeader dataset={dataset({ case_count: 0 })} version={null} {...handlers()} />);

    await openMenu();
    const csv = await screen.findByRole("menuitem", { name: "Export CSV" });
    expect(csv).toHaveAttribute("aria-disabled", "true");
  });

  it("imports the chosen file, and says why one was refused", async () => {
    const onImport = vi.fn().mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("row 3"));
    render(
      <DatasetHeader dataset={dataset()} version={null} onImport={onImport} {...handlers()} />,
    );
    const picker = screen.getByLabelText("Choose a CSV or JSONL file to import");
    const click = vi.spyOn(picker, "click");
    await openMenu();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Import" }));
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
