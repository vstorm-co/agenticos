import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { OdooSetupDialog } from "./odoo-setup-dialog";

const { hook, mutate } = vi.hoisted(() => ({ hook: vi.fn(), mutate: vi.fn() }));
vi.mock("@/hooks/use-connected-accounts", () => ({ useConnectedAccounts: hook }));
beforeEach(() => {
  vi.clearAllMocks();
  hook.mockReturnValue({ connectOdoo: { mutate, isPending: false } });
});
it("connects the selected owner with write access off by default", async () => {
  const close = vi.fn();
  render(<OdooSetupDialog owner="organization" onClose={close} />);
  expect(hook).toHaveBeenCalledWith("organization", { provider: "odoo" });
  await userEvent.type(screen.getByLabelText("Odoo HTTPS origin"), "https://erp.example.com");
  await userEvent.type(screen.getByLabelText("Database name"), "company");
  await userEvent.type(screen.getByLabelText("Odoo API key"), "test-key");
  await userEvent.type(screen.getByLabelText("Account label"), "ERP");
  await userEvent.click(screen.getByRole("button", { name: "Connect account" }));
  expect(mutate).toHaveBeenCalledWith(
    {
      credential: { origin: "https://erp.example.com", database: "company", api_key: "test-key" },
      label: "ERP",
      write: false,
    },
    expect.any(Object),
  );
  expect(close).not.toHaveBeenCalled();
  mutate.mock.calls[0]?.[1].onSuccess();
  expect(close).toHaveBeenCalledOnce();
});
it("lets a person opt into writes and keeps an in-flight connection disabled", async () => {
  hook.mockReturnValue({ connectOdoo: { mutate, isPending: true } });
  render(<OdooSetupDialog owner="personal" onClose={vi.fn()} />);
  const checkbox = screen.getByRole("checkbox");
  expect(checkbox).not.toBeChecked();
  await userEvent.click(checkbox);
  expect(checkbox).toBeChecked();
  expect(screen.getByRole("button", { name: "Connect account" })).toBeDisabled();
});
