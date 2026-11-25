import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AccountNotices } from "./account-notices";

vi.mock("@/components/orgs/received-invitations", () => ({
  ReceivedInvitations: () => <button>Invitations</button>,
}));

it("keeps invitations outside page content without adding a second setup reminder", () => {
  const { container } = render(<AccountNotices />);
  const overlay = container.querySelector("[data-account-notices]");
  expect(screen.getByRole("button", { name: "Invitations" }).parentElement).toBe(overlay);
  expect(overlay).toHaveTextContent(/^Invitations$/);
  expect(screen.queryByRole("link", { name: /setup|example/i })).not.toBeInTheDocument();
});
