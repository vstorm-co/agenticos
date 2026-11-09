import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { CasesToolbar } from "./cases-toolbar";
it("keeps creation, generation, import guidance and Activity beside the cases table", async () => {
  const add = vi.fn();
  const generate = vi.fn();
  const importFile = vi.fn().mockResolvedValue({});
  render(
    <CasesToolbar datasetId="dataset-1" onAdd={add} onGenerate={generate} onImport={importFile} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Add case" }));
  expect(add).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: "Generate cases" }));
  expect(generate).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: "More ways to add" }));
  expect(screen.getByRole("menuitem", { name: "Add from Activity" })).toHaveAttribute(
    "href",
    "/runs?dataset=dataset-1",
  );
  await userEvent.keyboard("{Escape}");
  await userEvent.click(screen.getByRole("button", { name: "Import" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("CSV or JSONL");
  await userEvent.click(screen.getByRole("button", { name: "Choose file" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  const file = new File(['{"input":"Refund?"}\n'], "cases.jsonl", { type: "application/x-ndjson" });
  await userEvent.upload(screen.getByLabelText("Choose a CSV or JSONL file to import"), file);
  await waitFor(() => expect(importFile).toHaveBeenCalledWith(file));
});
