import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { hunk } from "@/test-utils/authoring";
import { SuggestionCard } from "./suggestion-card";
import { ChangePreview } from "./result-dialog";

const proposal = hunk({
  kind: "create_skill",
  new_name: "return-procedure",
  new_description: "Handle returns consistently",
  new_text: "Check the order. Explain the window. Confirm the next step.",
  old_text: "",
});
it("previews the new resource and its binding before creation", () => {
  render(<ChangePreview hunk={proposal} />);
  expect(screen.getByText("Worth creating a skill")).toBeInTheDocument();
  expect(screen.getByText("return-procedure")).toBeInTheDocument();
  expect(screen.getByText(/Check the order/)).toBeInTheDocument();
  expect(screen.getByText(/grants no tools/)).toBeInTheDocument();
});
it("lets a person accept or dismiss the whole skill without editing its measured body", async () => {
  const decide = vi.fn();
  render(<SuggestionCard hunk={proposal} canEdit busy={false} onDecide={decide} />);
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  expect(decide).toHaveBeenLastCalledWith({ action: "accept" });
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(decide).toHaveBeenLastCalledWith({ action: "dismiss" });
});
it("explains the missing create permission and leaves dismissal available", () => {
  render(
    <SuggestionCard
      hunk={{ ...proposal, blocked: "create_skill_permission" }}
      canEdit
      busy={false}
      onDecide={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent(/requires skills:edit/);
  expect(screen.getByRole("button", { name: "Dismiss" })).toBeEnabled();
});
