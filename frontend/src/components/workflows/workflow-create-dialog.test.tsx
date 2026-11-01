import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WORKFLOW_TEMPLATES } from "@/lib/workflows/templates";
import { WorkflowCreateDialog } from "./workflow-create-dialog";
import { WorkflowTemplateDialog } from "./workflow-template-dialog";
vi.mock("@/components/sharing/audience-search", () => ({
  AudienceSearch: ({
    value,
    onChange,
  }: {
    value: { mode: "chosen"; group_ids: string[]; user_ids: string[] };
    onChange: (next: typeof value) => void;
  }) => (
    <button onClick={() => onChange({ ...value, user_ids: ["member"] })}>Choose colleague</button>
  ),
}));

describe("workflow creation", () => {
  it("requires a name, chooses access and waits for explicit creation", async () => {
    const onChoose = vi.fn();
    render(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={onChoose} busy={false} />);
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Customer onboarding");
    await userEvent.click(screen.getByRole("radio", { name: /Only me/ }));
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Webhook" }));
    expect(onChoose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    const choice = onChoose.mock.calls[0]![0];
    expect(choice).toMatchObject({
      name: "Customer onboarding",
      visibility: "private",
      description: null,
      tags: [],
      group_ids: [],
      user_ids: [],
    });
    expect(choice.graph.nodes).toEqual([
      expect.objectContaining({ definition_id: "trigger.webhook", id: choice.graph.entry_node_id }),
    ]);
  });

  it("preserves the chosen template and lets its name be changed before creation", async () => {
    const onChoose = vi.fn();
    render(
      <WorkflowCreateDialog
        open
        onOpenChange={vi.fn()}
        onChoose={onChoose}
        busy={false}
        initial={{ name: "Starter", graph: WORKFLOW_TEMPLATES[0]!.graph }}
      />,
    );
    await userEvent.clear(screen.getByRole("textbox", { name: "Name" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "My example");
    expect(onChoose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(onChoose).toHaveBeenCalledWith(
      expect.objectContaining({ name: "My example", graph: WORKFLOW_TEMPLATES[0]!.graph }),
    );
  });

  it("keeps creation disabled while saving", () => {
    render(
      <WorkflowCreateDialog
        open
        onOpenChange={vi.fn()}
        onChoose={vi.fn()}
        busy
        initial={{ name: "Starter", graph: null }}
      />,
    );
    expect(screen.getByRole("textbox", { name: "Name" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  });

  it("offers provisioned automations in a separate category gallery", async () => {
    const onChoose = vi.fn();
    render(
      <WorkflowTemplateDialog open onOpenChange={vi.fn()} onChoose={onChoose} canProvisionTables />,
    );
    expect(screen.queryByRole("button", { name: "Use" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Automations/ }));
    expect(screen.getByText("Markdown notebook")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Use" })[0]!);
    expect(onChoose).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Public API → table",
        graph: null,
        template_id: "publicApi",
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Categories" }));
    await userEvent.click(screen.getByRole("button", { name: /Examples/ }));
    expect(screen.getByText("Two-step sequence")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Use" })[0]!);
    expect(onChoose).toHaveBeenLastCalledWith(
      expect.objectContaining({ graph: WORKFLOW_TEMPLATES[0]!.graph }),
    );
  });

  it("blocks table-backed templates without table creation rights", async () => {
    render(
      <WorkflowTemplateDialog
        open
        onOpenChange={vi.fn()}
        onChoose={vi.fn()}
        canProvisionTables={false}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Automations/ }));
    for (const button of screen.getAllByRole("button", { name: "Use" }))
      expect(button).toBeDisabled();
  });
});

it("saves description and tags from the labeled optional section", async () => {
  const onChoose = vi.fn(),
    onOpenChange = vi.fn();
  const { rerender } = render(
    <WorkflowCreateDialog open onOpenChange={onOpenChange} onChoose={onChoose} busy={false} />,
  );
  await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Daily check");
  await userEvent.click(screen.getByRole("button", { name: "More options" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Description" }), "A daily check");
  await userEvent.type(screen.getByRole("textbox", { name: "Tags" }), "daily{Enter}");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  expect(onChoose).toHaveBeenCalledWith(
    expect.objectContaining({ description: "A daily check", tags: ["daily"] }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
  onOpenChange.mockClear();
  rerender(<WorkflowCreateDialog open onOpenChange={onOpenChange} onChoose={onChoose} busy />);
  await userEvent.keyboard("{Escape}");
  expect(onOpenChange).not.toHaveBeenCalled();
  fireEvent.submit(screen.getByRole("textbox", { name: "Name" }).closest("form")!);
  expect(onChoose).toHaveBeenCalledTimes(1);
});

it("lets a resource-backed template stay private and closes creation without saving", async () => {
  const onOpenChange = vi.fn();
  render(
    <WorkflowCreateDialog
      open
      onOpenChange={onOpenChange}
      onChoose={vi.fn()}
      busy={false}
      initial={{ name: "Notes", template_id: "markdownNotes", graph: null }}
    />,
  );
  expect(screen.getByRole("radio", { name: /Only me/ })).toHaveAttribute("aria-checked", "true");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  await userEvent.keyboard("{Escape}");
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

it("requires chosen people before saving a restricted audience", async () => {
  const onChoose = vi.fn();
  render(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={onChoose} busy={false} />);
  await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Finance check");
  await userEvent.click(screen.getByRole("radio", { name: /Some people/ }));
  expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Choose colleague" }));
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  expect(onChoose).toHaveBeenCalledWith(
    expect.objectContaining({ visibility: "private", user_ids: ["member"] }),
  );
});

it("closes the separate library with Escape", async () => {
  const onOpenChange = vi.fn();
  render(
    <WorkflowTemplateDialog
      open
      onOpenChange={onOpenChange}
      onChoose={vi.fn()}
      canProvisionTables
    />,
  );
  await userEvent.keyboard("{Escape}");
  expect(onOpenChange).toHaveBeenCalledWith(false);
});
