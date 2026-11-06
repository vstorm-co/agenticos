import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReplyMailboxPicker } from "./reply-mailbox-picker";

const state = vi.hoisted(() => ({
  error: null as Error | null,
  isLoading: false,
  items: [
    { portal: { key: "google", name: "Gmail" }, action: "create", connectionId: "g" },
    { portal: { key: "microsoft", name: "Outlook" }, action: "create", connectionId: "o" },
    { portal: { key: "github", name: "GitHub" }, action: "create", connectionId: "h" },
  ],
}));
vi.mock("@/hooks/use-portals", () => ({ usePortals: () => state }));
beforeEach(() => {
  state.error = null;
  state.isLoading = false;
});

describe("reply mailbox selection", () => {
  it("requires explicit account selection and maps Outlook to its mail provider", async () => {
    const change = vi.fn();
    render(<ReplyMailboxPicker value={undefined} onChange={change} />);
    expect(change).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("combobox", { name: "Connected mailbox" }));
    expect(screen.queryByRole("option", { name: "GitHub" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "Outlook" }));
    expect(change).toHaveBeenCalledWith({ connection_id: "o", provider: "outlook", mailbox: null });
  });
  it("shows fetch failure instead of implying no connected mailbox", () => {
    state.error = new Error("failed");
    render(<ReplyMailboxPicker value="g" onChange={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load mailboxes");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
  it("keeps read-only configuration disabled", () => {
    render(<ReplyMailboxPicker value="g" onChange={vi.fn()} disabled />);
    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});

it("shows a disconnected selected mailbox without silently replacing it", async () => {
  const change = vi.fn();
  render(<ReplyMailboxPicker value="disconnected" onChange={change} />);
  await userEvent.click(screen.getByRole("combobox", { name: "Connected mailbox" }));
  expect(screen.getByRole("option", { name: /unavailable|disconnected/i })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await userEvent.click(screen.getByRole("option", { name: "Gmail" }));
  expect(change).toHaveBeenCalledWith({ connection_id: "g", provider: "google", mailbox: null });
});

it("waits for the mailbox catalog without claiming no account is connected", () => {
  state.isLoading = true;
  render(<ReplyMailboxPicker value={null} onChange={vi.fn()} />);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
