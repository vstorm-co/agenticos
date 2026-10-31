import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import messages from "@/../messages/en.json";
import { WORKFLOW_TEMPLATES } from "@/lib/workflows/templates";
import { WorkflowCreateDialog } from "./workflow-create-dialog";

function wrap(node: ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={messages}>
      {node}
    </NextIntlClientProvider>
  );
}

describe("WorkflowCreateDialog", () => {
  it("offers every way a workflow starts and every shipped template", async () => {
    render(
      wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={vi.fn()} busy={false} />),
    );
    for (const start of [
      "Manual",
      "API request",
      "Chat message",
      "Webhook",
      "Schedule",
      "Table record",
    ]) {
      expect(screen.getByText(start)).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Use" })).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Templates" }));
    // "Use" appears once per template.
    expect(screen.getAllByRole("button", { name: "Use" })).toHaveLength(WORKFLOW_TEMPLATES.length);
    for (const automation of ["Public API → table", "Markdown notebook"]) {
      expect(screen.getByText(automation)).toBeInTheDocument();
    }
  });

  it("offers Outlook as a way to start", async () => {
    render(
      wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={vi.fn()} busy={false} />),
    );
    expect(screen.queryByText("Outlook")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More ways to start" }));
    expect(screen.getByText("Outlook")).toBeInTheDocument();
    expect(screen.getByText(/connected Microsoft 365 mailbox starts a run/)).toBeInTheDocument();
  });

  it("starts a new workflow from the trigger chosen, as its entry and only node", async () => {
    const onChoose = vi.fn();
    render(
      wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={onChoose} busy={false} />),
    );

    await userEvent.click(screen.getByText("Webhook"));

    const [{ name, graph }] = onChoose.mock.calls[0]!;
    expect(name).toBe("Untitled workflow");
    expect(graph.nodes).toEqual([
      expect.objectContaining({ id: graph.entry_node_id, definition_id: "trigger.webhook" }),
    ]);
    expect([graph.edges, graph.bindings]).toEqual([[], []]);
  });

  it("chooses a template's seed graph", async () => {
    const onChoose = vi.fn();
    render(
      wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={onChoose} busy={false} />),
    );

    await userEvent.click(screen.getByRole("tab", { name: "Templates" }));
    const [firstUse] = screen.getAllByRole("button", { name: "Use" });
    await userEvent.click(firstUse!);

    expect(onChoose).toHaveBeenCalledWith({
      name: "Starter",
      graph: WORKFLOW_TEMPLATES[0]!.graph,
    });
  });

  it("disables its controls while a create is in flight", async () => {
    render(wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={vi.fn()} busy />));

    await userEvent.click(screen.getByRole("tab", { name: "Templates" }));
    for (const button of screen.getAllByRole("button", { name: "Use" })) {
      expect(button).toBeDisabled();
    }
  });
});

it("requests a provisioned template instead of an unresolved graph", async () => {
  const onChoose = vi.fn();
  render(
    wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={onChoose} busy={false} />),
  );
  await userEvent.click(screen.getByRole("tab", { name: "Templates" }));
  await userEvent.click(screen.getByRole("button", { name: /Public API → table/ }));
  expect(onChoose).toHaveBeenCalledWith({
    name: "Public API → table",
    graph: null,
    template_id: "publicApi",
  });
});
