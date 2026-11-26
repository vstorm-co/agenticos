import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { IntegrationAccountFields } from "./integration-account-fields";

const accounts = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-connected-accounts", () => ({ useConnectedAccounts: accounts }));
beforeEach(() => {
  vi.clearAllMocks();
  accounts.mockReturnValue({
    accounts: [{ id: "org-account", email: "work@example.com", label: "Work" }],
    isLoading: false,
    error: null,
  });
});
it("binds each user's accounts without asking the author for an account name", () => {
  const change = vi.fn();
  render(
    <IntegrationAccountFields productId="gmail" provider="google" config={{}} onChange={change} />,
  );
  expect(screen.getByRole("combobox", { name: "Whose accounts to use" })).toHaveTextContent(
    "Each user’s connected accounts",
  );
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(
    screen.getByText("Each person connects their own accounts in chat or profile settings."),
  ).toBeInTheDocument();
  expect(accounts).toHaveBeenCalledWith("personal", { provider: "google", enabled: false });
  expect(screen.getByRole("link", { name: "Manage connected accounts" })).toHaveAttribute(
    "href",
    "/settings/profile",
  );
  expect(change).not.toHaveBeenCalled();
});
it("selects organization accounts by label and stores only their IDs", async () => {
  const change = vi.fn();
  render(
    <IntegrationAccountFields
      productId="gmail"
      provider="google"
      config={{ account: "organization" }}
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("checkbox", { name: "Work — work@example.com" }));
  expect(change).toHaveBeenCalledWith({
    account: "organization",
    connection_id: null,
    connection_ids: ["org-account"],
  });
  expect(accounts).toHaveBeenCalledWith("organization", { provider: "google", enabled: true });
});
it("clears an account reference when its owner changes", async () => {
  const change = vi.fn();
  render(
    <IntegrationAccountFields
      productId="gmail"
      provider="google"
      config={{ account: "organization", connection_id: "org-account" }}
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("combobox", { name: "Whose accounts to use" }));
  await userEvent.click(screen.getByRole("option", { name: "Each user’s connected accounts" }));
  expect(change).toHaveBeenCalledWith({
    account: "personal",
    account_name: "",
    connection_id: null,
    connection_ids: [],
  });
});
it("makes a read-only capability unable to change accounts", () => {
  render(
    <IntegrationAccountFields
      productId="gmail"
      provider="google"
      config={{}}
      onChange={vi.fn()}
      disabled
    />,
  );
  expect(screen.getByRole("combobox", { name: "Whose accounts to use" })).toBeDisabled();
  expect(accounts).toHaveBeenCalledWith("personal", { provider: "google", enabled: false });
});

it("shows a publish refusal beside the account field", () => {
  render(
    <IntegrationAccountFields
      productId="gmail"
      provider="google"
      config={{ account: "organization" }}
      onChange={vi.fn()}
      configErrors={{ connection_id: "Choose an account in this organization" }}
    />,
  );
  expect(screen.getByText("Choose an account in this organization")).toBeInTheDocument();
});

it("preserves a saved account restriction until its author explicitly removes it", async () => {
  const change = vi.fn();
  render(
    <IntegrationAccountFields
      productId="gmail"
      provider="google"
      config={{ account_name: "Work" }}
      onChange={change}
    />,
  );
  expect(
    screen.getByText("This saved configuration restricts user accounts to “Work”."),
  ).toBeInTheDocument();
  expect(change).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Remove account filter" }));
  expect(change).toHaveBeenCalledWith({ account_name: "" });
});

it("keeps a legacy organization account selected when another one is added", async () => {
  accounts.mockReturnValue({
    accounts: [
      { id: "one", email: "one@example.com", label: "Work" },
      { id: "two", email: "two@example.com", label: "Work" },
    ],
    isLoading: false,
    error: null,
  });
  const change = vi.fn();
  render(
    <IntegrationAccountFields
      productId="gmail"
      provider="google"
      config={{ account: "organization", connection_id: "one" }}
      onChange={change}
    />,
  );
  expect(screen.getByRole("checkbox", { name: "Work — one@example.com" })).toBeChecked();
  await userEvent.click(screen.getByRole("checkbox", { name: "Work — two@example.com" }));
  expect(change).toHaveBeenCalledWith({
    account: "organization",
    connection_id: null,
    connection_ids: ["one", "two"],
  });
});

it("removes only the unchecked organization account and shows an unlabeled account by email", async () => {
  accounts.mockReturnValue({
    accounts: [{ id: "one", email: "one@example.com", label: null }],
    isLoading: false,
    error: null,
  });
  const change = vi.fn();
  render(
    <IntegrationAccountFields
      productId="gmail"
      provider="google"
      config={{ account: "organization", connection_ids: ["one", "two"] }}
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("checkbox", { name: "one@example.com" }));
  expect(change).toHaveBeenCalledWith({
    account: "organization",
    connection_id: null,
    connection_ids: ["two"],
  });
});
