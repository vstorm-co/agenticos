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
  it("offers a blank canvas and every shipped template", () => {
    render(
      wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={vi.fn()} busy={false} />),
    );
    expect(screen.getByText("Blank workflow")).toBeInTheDocument();
    // "Use" appears once per template.
    expect(screen.getAllByRole("button", { name: "Use" })).toHaveLength(WORKFLOW_TEMPLATES.length);
  });

  it("chooses a blank draft with no seed graph", async () => {
    const onChoose = vi.fn();
    render(
      wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={onChoose} busy={false} />),
    );

    await userEvent.click(screen.getByText("Blank workflow"));

    expect(onChoose).toHaveBeenCalledWith({ name: "Untitled workflow", graph: null });
  });

  it("chooses a template's seed graph", async () => {
    const onChoose = vi.fn();
    render(
      wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={onChoose} busy={false} />),
    );

    const [firstUse] = screen.getAllByRole("button", { name: "Use" });
    await userEvent.click(firstUse!);

    expect(onChoose).toHaveBeenCalledWith({
      name: "Starter",
      graph: WORKFLOW_TEMPLATES[0]!.graph,
    });
  });

  it("disables its controls while a create is in flight", () => {
    render(wrap(<WorkflowCreateDialog open onOpenChange={vi.fn()} onChoose={vi.fn()} busy />));

    for (const button of screen.getAllByRole("button", { name: "Use" })) {
      expect(button).toBeDisabled();
    }
  });
});
