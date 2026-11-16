import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { DelegationSheet, type SheetDelegation } from "./delegation-sheet";

const permission = vi.hoisted(() => ({ allowed: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => permission.allowed }),
}));

const item: SheetDelegation = {
  key: "task",
  delegate: { id: null, slug: "reviewer", name: "Reviewer" },
  status: "completed",
  brief: "Check the changes",
  answer: "Checked",
  runId: "child-run",
  outputTokens: 25,
};

it.each([true, false])("gates the child run link on run access (%s)", (allowed) => {
  permission.allowed = allowed;
  render(<DelegationSheet items={[item]} opened="task" onOpen={() => {}} onClose={() => {}} />);
  expect(screen.getByText("0 input · 25 output tokens")).toBeInTheDocument();
  const link = screen.queryByRole("link", { name: "Open in run history" });
  if (allowed) expect(link).toHaveAttribute("href", "/runs?run=child-run");
  else expect(link).toBeNull();
});
