import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SecretPicker } from "./secret-picker";

const useSecretsMock = vi.fn();

vi.mock("@/hooks", () => ({
  useSecrets: () => useSecretsMock(),
}));

const SECRETS = [
  { id: "s1", name: "OpenAI", kind: "api_key" },
  { id: "s2", name: "AWS", kind: "aws_credentials" },
];

beforeEach(() => {
  vi.clearAllMocks();
  useSecretsMock.mockReturnValue({ secrets: SECRETS, isLoading: false });
});

function mount(
  value: string | null,
  props: Partial<{ disabled: boolean; error: string; kind: "api_key" }> = {},
) {
  const onChange = vi.fn();
  render(<SecretPicker value={value} onChange={onChange} {...props} />);
  return onChange;
}

describe("SecretPicker", () => {
  it("writes the chosen secret's id and never a value", async () => {
    const onChange = mount(null);

    await userEvent.click(screen.getByRole("combobox", { name: "Secret" }));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI/ }));

    expect(onChange).toHaveBeenCalledWith("s1");
  });

  it("offers only secrets of the required kind", async () => {
    mount(null, { kind: "api_key" });

    await userEvent.click(screen.getByRole("combobox", { name: "Secret" }));

    expect(screen.getByRole("option", { name: /OpenAI/ })).toBeVisible();
    expect(screen.queryByRole("option", { name: /AWS/ })).toBeNull();
  });

  it("keeps a referenced secret visible when it names none the caller can see", () => {
    mount("gone");

    expect(screen.getByText("The referenced secret is no longer available.")).toBeVisible();
    expect(screen.getByText("gone")).toBeVisible();
  });

  it("says so when the vault is empty and offers a way to store one", () => {
    useSecretsMock.mockReturnValue({ secrets: [], isLoading: false });
    mount(null);

    expect(screen.getByText("No secrets stored yet.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Store a secret in the vault" })).toBeVisible();
  });

  it("shows a field-scoped validation message", () => {
    mount("s1", { error: "Required" });
    expect(screen.getByText("Required")).toBeVisible();
  });

  it("is inert for a caller who may not edit the workflow", () => {
    mount("s1", { disabled: true });
    expect(screen.getByRole("combobox", { name: "Secret" })).toBeDisabled();
  });

  it("draws no empty or orphaned notice while the vault is still loading", () => {
    useSecretsMock.mockReturnValue({ secrets: [], isLoading: true });
    mount("gone");

    expect(screen.queryByText("No secrets stored yet.")).toBeNull();
    expect(screen.queryByText("The referenced secret is no longer available.")).toBeNull();
  });
});
