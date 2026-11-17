import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ConnectedAccountPicker } from "./connected-account-picker";

const services = [
  ["Gmail", "google", "gmail"],
  ["Google Calendar", "google", "google_calendar"],
  ["Google Drive", "google", "google_drive"],
  ["Google Docs", "google", "google_docs"],
  ["Google Sheets", "google", "google_sheets"],
  ["Google Slides", "google", "google_slides"],
  ["Outlook mail", "microsoft", "outlook_mail"],
  ["Outlook Calendar", "microsoft", "outlook_calendar"],
  ["OneDrive / SharePoint", "microsoft", "microsoft_files"],
  ["Excel", "microsoft", "excel"],
  ["Word", "microsoft", "word"],
  ["Teams", "microsoft", "teams"],
] as const;

it.each(services)("selects only %s before provider consent", async (name, provider, product) => {
  const select = vi.fn();
  render(<ConnectedAccountPicker onSelect={select} onClose={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "Google" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Microsoft" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name }));
  expect(select).toHaveBeenCalledExactlyOnceWith({
    owner: "personal",
    provider,
    products: [product],
  });
});

it.each(["Slack", "IMAP", "Odoo"])("keeps %s available with its existing setup", async (name) => {
  const select = vi.fn();
  render(<ConnectedAccountPicker onSelect={select} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name }));
  expect(select).toHaveBeenCalledExactlyOnceWith({
    owner: "personal",
    provider: name.toLowerCase(),
  });
});

it("keeps organization ownership when choosing an individual service", async () => {
  const select = vi.fn();
  render(
    <ConnectedAccountPicker
      allowOrganization
      initialOwner="organization"
      onSelect={select}
      onClose={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Excel" }));
  expect(select).toHaveBeenLastCalledWith({
    owner: "organization",
    provider: "microsoft",
    products: ["excel"],
  });
  await userEvent.click(screen.getByRole("radio", { name: "My account" }));
  await userEvent.click(screen.getByRole("button", { name: "Gmail" }));
  expect(select).toHaveBeenLastCalledWith({
    owner: "personal",
    provider: "google",
    products: ["gmail"],
  });
});

it("restricts profile connections to personal ownership and supports keyboard selection", async () => {
  const select = vi.fn();
  render(
    <ConnectedAccountPicker initialOwner="organization" onSelect={select} onClose={vi.fn()} />,
  );
  expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  screen.getByRole("button", { name: "Gmail" }).focus();
  await userEvent.keyboard("{Enter}");
  expect(select).toHaveBeenCalledExactlyOnceWith({
    owner: "personal",
    provider: "google",
    products: ["gmail"],
  });
});

it("dismisses the picker without starting a connection", async () => {
  const close = vi.fn();
  const select = vi.fn();
  render(<ConnectedAccountPicker onSelect={select} onClose={close} />);
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalledOnce();
  expect(select).not.toHaveBeenCalled();
});
