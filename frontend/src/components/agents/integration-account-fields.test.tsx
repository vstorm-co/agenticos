import { fireEvent, render, screen } from "@testing-library/react";
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
it("keeps a personal label portable across the people running an agent", async () => {
  const change = vi.fn();
  render(
    <IntegrationAccountFields productId="gmail" provider="google" config={{}} onChange={change} />,
  );
  await userEvent.type(screen.getByLabelText("Personal account name"), "W");
  expect(change).toHaveBeenLastCalledWith({ account_name: "W" });
  expect(accounts).toHaveBeenCalledWith("personal", { provider: "google", enabled: true });
  expect(screen.getByRole("link", { name: "Manage connected accounts" })).toHaveAttribute(
    "href",
    "/vault",
  );
});
it("selects an organization account by its label and stores its ID", async () => {
  const change = vi.fn();
  render(
    <IntegrationAccountFields
      productId="gmail"
      provider="google"
      config={{ account: "organization" }}
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("combobox", { name: "Choose a connected account" }));
  await userEvent.click(screen.getByRole("option", { name: "Work" }));
  expect(change).toHaveBeenCalledWith({ account: "organization", connection_id: "org-account" });
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
  await userEvent.click(screen.getByRole("combobox", { name: "Account owner" }));
  await userEvent.click(screen.getByRole("option", { name: "Your connected accounts" }));
  expect(change).toHaveBeenCalledWith({
    account: "personal",
    account_name: "",
    connection_id: null,
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
  expect(screen.getByLabelText("Personal account name")).toBeDisabled();
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

it("submits the unique account name when two personal accounts share a label", () => {
  accounts.mockReturnValue({
    accounts: [
      { id: "one", name: "google-account-one", label: "Work", email: "one@example.com" },
      { id: "two", name: "google-account-two", label: "Work", email: "two@example.com" },
    ],
    isLoading: false,
    error: null,
  });
  const change = vi.fn();
  render(
    <IntegrationAccountFields productId="gmail" provider="google" config={{}} onChange={change} />,
  );
  const options = screen.getAllByRole("option", { hidden: true });
  expect(options.map((option) => option.getAttribute("value"))).toEqual([
    "google-account-one",
    "google-account-two",
  ]);
  expect(options[1]).toHaveTextContent("Work — two@example.com");
  fireEvent.change(screen.getByLabelText("Personal account name"), {
    target: { value: "google-account-two" },
  });
  expect(change).toHaveBeenCalledWith({ account_name: "google-account-two" });
});
