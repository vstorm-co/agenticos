import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SecretPicker } from "./secret-picker";

const useSecretsMock = vi.fn();

const can = vi.fn();
vi.mock("@/hooks", () => ({
  useSecrets: () => useSecretsMock(),
  usePermissions: () => ({ can }),
}));
vi.mock("@/components/vault/secret-dialog", () => ({
  AddSecretDialog: ({
    open,
    kind,
    onSubmit,
  }: {
    open: boolean;
    kind?: string;
    onSubmit: (data: object) => Promise<unknown>;
  }) =>
    open ? (
      <button type="button" onClick={() => void onSubmit({ name: "new" })}>
        store {kind ?? "any kind"}
      </button>
    ) : null,
}));

const mutateAsync = vi.fn();
const KINDS = [{ kind: "api_key" }, { kind: "http_credential" }];

const SECRETS = [
  { id: "s1", name: "OpenAI", kind: "api_key" },
  { id: "s2", name: "AWS", kind: "aws_credentials" },
];

beforeEach(() => {
  vi.clearAllMocks();
  can.mockReturnValue(true);
  mutateAsync.mockResolvedValue({ id: "s-new" });
  useSecretsMock.mockReturnValue(vault(SECRETS));
});

function vault(secrets: typeof SECRETS, isLoading = false) {
  return { secrets, kinds: KINDS, isLoading, create: { mutateAsync, isPending: false } };
}

function mount(
  value: string | null,
  props: Partial<{ disabled: boolean; error: string; kind: string; label: string }> = {},
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

  it("is called what its field is called, when the field names itself", () => {
    mount(null, { label: "TypeSafe key" });
    expect(screen.getByRole("combobox", { name: "TypeSafe key" })).toBeTruthy();
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
    useSecretsMock.mockReturnValue(vault([]));
    mount(null);

    expect(screen.getByText("No secrets stored yet.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the vault" })).toBeVisible();
  });

  it("stores a new secret of the field's kind and chooses it", async () => {
    const onChange = mount(null, { kind: "http_credential" });

    await userEvent.click(screen.getByRole("button", { name: "New secret" }));
    await userEvent.click(screen.getByRole("button", { name: "store http_credential" }));

    expect(mutateAsync).toHaveBeenCalledWith({ name: "new" });
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledWith("s-new"));
  });

  it("opens the whole vault form for a field that names no kind", async () => {
    mount(null);
    await userEvent.click(screen.getByRole("button", { name: "New secret" }));
    expect(screen.getByRole("button", { name: "store any kind" })).toBeVisible();
  });

  it("offers no new secret for a kind this build has no form for, or without the right", () => {
    mount(null, { kind: "future_kind" });
    expect(screen.queryByRole("button", { name: "New secret" })).toBeNull();
  });

  it("offers no new secret to a member who may not store one", () => {
    can.mockReturnValue(false);
    mount(null);
    expect(screen.queryByRole("button", { name: "New secret" })).toBeNull();
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
    useSecretsMock.mockReturnValue(vault([], true));
    mount("gone");

    expect(screen.queryByText("No secrets stored yet.")).toBeNull();
    expect(screen.queryByText("The referenced secret is no longer available.")).toBeNull();
  });
});
