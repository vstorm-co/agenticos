import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { PageHeader } from "./page-header";

vi.mock("@/components/onboarding/restart-tour-button", () => ({ RestartTourButton: () => null }));

it("opens secondary commands without replacing the primary action and closes on Escape", async () => {
  const command = vi.fn();
  render(
    <PageHeader
      title="Workflows"
      actions={<button>Create workflow</button>}
      secondaryActions={<button onClick={command}>Import workflow</button>}
    />,
  );
  const toggle = screen.getByRole("button", { name: "More page actions" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  await userEvent.click(screen.getByRole("button", { name: "Import workflow" }));
  expect(command).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Create workflow" })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveFocus();
  await userEvent.click(toggle);
  await userEvent.click(screen.getByRole("heading", { name: "Workflows" }));
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  await userEvent.click(document.body);
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});
