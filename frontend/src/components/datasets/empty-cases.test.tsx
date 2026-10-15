import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EmptyCases } from "./empty-cases";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-datasets", () => ({ exportDataset: vi.fn() }));

describe("EmptyCases", () => {
  it("offers the three ways a case arrives to somebody who may add one", async () => {
    const onAddCase = vi.fn();
    const onImport = vi.fn().mockResolvedValue({});
    render(<EmptyCases datasetId="d1" onAddCase={onAddCase} onImport={onImport} />);

    await userEvent.click(screen.getByRole("button", { name: "Add case" }));
    expect(onAddCase).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Add from Activity" })).toHaveAttribute(
      "href",
      "/runs?dataset=d1",
    );

    const picker = screen.getByLabelText("Choose a CSV or JSONL file to import");
    const click = vi.spyOn(picker, "click");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(click).toHaveBeenCalled();
    const file = new File(["input\nq\n"], "cases.csv", { type: "text/csv" });
    await userEvent.upload(picker, file);
    await waitFor(() => expect(onImport).toHaveBeenCalledWith(file));
  });

  it("says only what the tab holds to somebody who may not add a case", () => {
    render(<EmptyCases datasetId="d1" />);

    expect(screen.getByText("No cases in this version")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
