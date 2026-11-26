import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkflowTemplateDialog } from "./workflow-template-dialog";

it("uses the shared category library and preserves workflow selection payloads", async () => {
  const choose = vi.fn();
  render(
    <WorkflowTemplateDialog open onOpenChange={vi.fn()} onChoose={choose} canProvisionTables />,
  );
  expect(screen.getByRole("dialog")).toHaveAccessibleName("Workflow templates");
  await userEvent.click(screen.getByRole("button", { name: /Automations/ }));
  expect(screen.getByRole("dialog")).toHaveAccessibleName("Automations");
  const row = screen.getByRole("heading", { name: "Public API → table" }).parentElement
    ?.parentElement;
  if (!row) throw new Error("Expected a template row");
  await userEvent.click(within(row).getByRole("button", { name: "Use" }));
  expect(choose).toHaveBeenCalledWith(
    expect.objectContaining({ template_id: "publicApi", graph: null, name: "Public API → table" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Categories" }));
  await userEvent.click(screen.getByRole("button", { name: /Examples/ }));
  expect(screen.getByRole("dialog")).toHaveAccessibleName("Examples");
  expect(screen.getByRole("heading", { name: "Starter" })).toBeVisible();
});
it("keeps table-backed templates blocked with visible reasons and still allows await reply", async () => {
  const choose = vi.fn();
  render(
    <WorkflowTemplateDialog
      open
      onOpenChange={vi.fn()}
      onChoose={choose}
      canProvisionTables={false}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: /Automations/ }));
  const use = screen.getAllByRole("button", { name: "Use" });
  expect(use[0]).toBeDisabled();
  expect(use[1]).toBeDisabled();
  expect(screen.getAllByText("Requires permission to create and edit tables.")).toHaveLength(2);
  expect(use[2]).toBeEnabled();
  await userEvent.click(use[2]!);
  expect(choose).toHaveBeenCalledWith(expect.objectContaining({ template_id: "awaitReply" }));
});
it("resets category browsing after the library is dismissed", async () => {
  const close = vi.fn();
  const view = render(
    <WorkflowTemplateDialog open onOpenChange={close} onChoose={vi.fn()} canProvisionTables />,
  );
  await userEvent.click(screen.getByRole("button", { name: /Examples/ }));
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalledWith(false);
  view.rerender(
    <WorkflowTemplateDialog
      open={false}
      onOpenChange={close}
      onChoose={vi.fn()}
      canProvisionTables
    />,
  );
  view.rerender(
    <WorkflowTemplateDialog open onOpenChange={close} onChoose={vi.fn()} canProvisionTables />,
  );
  expect(screen.getByRole("dialog")).toHaveAccessibleName("Workflow templates");
});
