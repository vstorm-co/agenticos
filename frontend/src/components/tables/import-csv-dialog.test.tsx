import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportCsvDialog } from "./import-csv-dialog";
import { apiClient, ApiError } from "@/lib/api-client";
import type { ColumnDef } from "@/types/tables";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { post: vi.fn() } };
});

const base = { nullable: true, default: null, options: [], archived: false };
const columns: ColumnDef[] = [
  { ...base, id: "name", label: "Name", type: "text" },
  { ...base, id: "seats", label: "Seats", type: "integer" },
];

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderDialog(onOpenChange = vi.fn()) {
  render(<ImportCsvDialog tableId="t1" columns={columns} open onOpenChange={onOpenChange} />, {
    wrapper,
  });
  return onOpenChange;
}

async function choose(content: string) {
  const input = screen.getByLabelText("Choose a CSV file");
  await act(async () => {
    fireEvent.change(input, { target: { files: [new File([content], "people.csv")] } });
  });
}

const sent = () =>
  vi
    .mocked(apiClient.post)
    .mock.calls.map(
      ([, body]) => (body as { records: { external_id: string | null; values: object }[] }).records,
    );

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("ImportCsvDialog", () => {
  it("says so when a file holds no rows", async () => {
    renderDialog();

    await choose("Name,Seats\n,\n");

    expect(screen.getByText("That file has no rows under its header.")).toBeInTheDocument();
  });

  it("maps the file's columns by name, sends what reads and lists what does not", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      created: 1,
      failed: [{ index: 1, code: "ALREADY_EXISTS", message: "Taken", details: null }],
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const user = userEvent.setup();
    renderDialog();

    await choose("Name,Seats,External ID,Notes\nAcme,3,a-1,x\nGlobex,lots,a-2,y\nInitech,,a-3,z\n");
    expect(screen.getByText("3 rows in people.csv.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Where Name goes" })).toHaveTextContent("Name");
    expect(screen.getByRole("combobox", { name: "Where External ID goes" })).toHaveTextContent(
      "External id",
    );
    expect(screen.getByRole("combobox", { name: "Where Notes goes" })).toHaveTextContent(
      "Don't import",
    );
    expect(screen.getByText("Acme · Globex · Initech")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Import 3 rows" }));

    expect(await screen.findByText("1 record added.")).toBeInTheDocument();
    expect(sent()).toEqual([
      [
        { external_id: "a-1", values: { name: "Acme", seats: 3 } },
        { external_id: "a-3", values: { name: "Initech" } },
      ],
    ]);
    expect(screen.getByText("2 rows were not imported:")).toBeInTheDocument();
    expect(screen.getByText("Seats: not a number")).toBeInTheDocument();
    expect(screen.getByText("Taken")).toBeInTheDocument();
    expect(screen.getByText("Line 3:")).toBeInTheDocument();
    expect(screen.getByText("Line 4:")).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["tables", "t1", "records"] });
  });

  it("sends a long file in batches, and lists every row not sent once a batch is refused", async () => {
    let release!: () => void;
    vi.mocked(apiClient.post)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            release = () => resolve({ created: 200, failed: [] });
          }),
      )
      .mockRejectedValueOnce(new ApiError(429, "Too many table writes"));
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    renderDialog(onOpenChange);
    const rows = Array.from({ length: 250 }, (_, i) => `Row ${i},${i}`).join("\n");

    await choose(`Name,Seats\n${rows}\n`);
    await user.click(screen.getByRole("button", { name: "Import 250 rows" }));
    expect(await screen.findByText("0 of 250 sent")).toBeInTheDocument();
    // An import in progress cannot be closed out from under itself.
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(onOpenChange).not.toHaveBeenCalled();
    await act(async () => release());

    expect(await screen.findByText("200 records added.")).toBeInTheDocument();
    expect(sent().map((batch) => batch.length)).toEqual([200, 50]);
    expect(screen.getByText("50 rows were not imported:")).toBeInTheDocument();
    expect(screen.getAllByText("Too many table writes")).toHaveLength(50);
    expect(screen.queryByText(/more\./)).not.toBeInTheDocument();
  });

  it("offers no import while every column is skipped, and goes back to choose again", async () => {
    const user = userEvent.setup();
    renderDialog();

    await choose("Other\nx\n");
    expect(screen.getByRole("button", { name: "Import 1 row" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Choose a CSV file")).toBeInTheDocument();
  });

  it("changes where a column goes, and lists at most fifty failures", async () => {
    const user = userEvent.setup();
    const onOpenChange = renderDialog();
    const rows = Array.from({ length: 60 }, (_, i) => `n${i}`).join("\n");

    await choose(`Count\n${rows}\n`);
    await user.click(screen.getByRole("combobox", { name: "Where Count goes" }));
    await user.click(screen.getByRole("option", { name: "Seats" }));
    await user.click(screen.getByRole("button", { name: "Import 60 rows" }));

    expect(await screen.findByText("No records were added.")).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.getAllByText("Seats: not a number")).toHaveLength(50);
    expect(screen.getByText("And 10 more.")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Close" })[0] as HTMLElement);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("names a column without a header", async () => {
    renderDialog();
    await choose(",Name\nx,Acme\n");
    expect(screen.getByText("Unnamed column")).toBeInTheDocument();
  });

  it("ignores a file input left empty", () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText("Choose a CSV file"), { target: { files: [] } });
    expect(screen.getByLabelText("Choose a CSV file")).toBeInTheDocument();
  });
});
