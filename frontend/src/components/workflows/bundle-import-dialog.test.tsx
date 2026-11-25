import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkflowImportEntryDialog } from "./bundle-import-dialog";
vi.mock("@/components/portability/resource-import-dialog", () => ({
  ImportResourceDialog: ({
    rootKind,
    onLegacy,
    onOpenChange,
  }: {
    rootKind: string;
    onLegacy: () => void;
    onOpenChange: (open: boolean) => void;
  }) => (
    <div>
      <span>{rootKind}</span>
      <button onClick={onLegacy}>Older format</button>
      <button onClick={() => onOpenChange(false)}>Close bundle</button>
    </div>
  ),
}));
vi.mock("./import-dialog", () => ({
  ImportWorkflowDialog: ({ onOpenChange }: { onOpenChange: (open: boolean) => void }) => (
    <div>
      <button onClick={() => onOpenChange(true)}>Keep legacy open</button>
      <button onClick={() => onOpenChange(false)}>Close legacy</button>
    </div>
  ),
}));
it("opens selective workflow import by default and resets the legacy mode after closing", async () => {
  const change = vi.fn();
  const { rerender } = render(<WorkflowImportEntryDialog open onOpenChange={change} />);
  expect(screen.getByText("workflow")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Older format" }));
  await userEvent.click(screen.getByRole("button", { name: "Keep legacy open" }));
  expect(change).toHaveBeenLastCalledWith(true);
  await userEvent.click(screen.getByRole("button", { name: "Close legacy" }));
  expect(change).toHaveBeenLastCalledWith(false);
  rerender(<WorkflowImportEntryDialog open onOpenChange={change} />);
  expect(screen.getByText("workflow")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Close bundle" }));
  expect(change).toHaveBeenLastCalledWith(false);
});
