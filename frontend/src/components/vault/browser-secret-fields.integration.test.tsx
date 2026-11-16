import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SecretFields, isSecretComplete } from "./secret-form";
import type { SecretKindInfo } from "@/types/secrets";
import { LOGIN, PROFILE } from "@/test-utils/browser-credential-fixtures";

function Form({
  info,
  initial,
  onChange = () => undefined,
}: {
  info: SecretKindInfo;
  initial: Record<string, unknown>;
  onChange?: (value: Record<string, unknown>) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <SecretFields
      info={info}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
      idPrefix="browser-secret"
    />
  );
}

describe("typed browser credentials", () => {
  it("keeps malformed optional initial values blank instead of displaying an object", () => {
    const view = render(
      <SecretFields info={LOGIN} value={{ totp: {} }} onChange={vi.fn()} idPrefix="empty-totp" />,
    );
    expect(screen.getByLabelText("Verification code seed")).toHaveValue("");
    view.rerender(
      <SecretFields
        info={PROFILE}
        value={{ fields: { email: null } }}
        onChange={vi.fn()}
        idPrefix="empty-profile"
      />,
    );
    expect(screen.getByRole("textbox", { name: "Email" })).toHaveValue("");
  });

  it("writes typed TOTP settings and erases the seed when verification codes are removed", async () => {
    const changed = vi.fn();
    render(
      <Form
        info={LOGIN}
        initial={{ allowed_origins: ["https://accounts.example"], username: "demo", password: "p" }}
        onChange={changed}
      />,
    );
    const enable = screen.getByRole("checkbox", { name: "Include a verification code (TOTP)" });
    await userEvent.click(enable);
    await userEvent.type(screen.getByLabelText("Verification code seed"), "JBSWY3DPEHPK3PXP");
    for (const [label, option] of [
      ["Code algorithm", "SHA256"],
      ["Code digits", "8"],
      ["Code period", "60 seconds"],
    ]) {
      await userEvent.click(screen.getByRole("combobox", { name: label }));
      await userEvent.click(screen.getByRole("option", { name: option }));
    }
    expect(changed).toHaveBeenLastCalledWith(
      expect.objectContaining({
        totp: { seed: "JBSWY3DPEHPK3PXP", algorithm: "SHA256", digits: 8, period_seconds: 60 },
      }),
    );
    await userEvent.click(enable);
    expect(changed.mock.calls.at(-1)![0]).not.toHaveProperty("totp");
    expect(screen.queryByLabelText("Verification code seed")).not.toBeInTheDocument();
  });

  it("masks login fields, names nested server refusals and respects disabled controls", () => {
    render(
      <SecretFields
        info={LOGIN}
        value={{
          username: 7,
          password: null,
          totp: { seed: "JBSWY3DPEHPK3PXP", algorithm: "SHA1", digits: 6, period_seconds: 30 },
        }}
        onChange={vi.fn()}
        idPrefix="refused"
        disabled
        errors={{
          allowed_origins: "Destination refused",
          "totp.seed": "Seed refused",
          "totp.digits": "Digits refused",
          totp: "Code configuration refused",
        }}
      />,
    );
    expect(screen.getByLabelText("Username")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Username")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Verification code seed")).toBeInvalid();
    expect(screen.getByRole("combobox", { name: "Code digits" })).toBeInvalid();
    expect(screen.getByRole("textbox", { name: "Allowed origins" })).toBeDisabled();
    expect(screen.getByText("Code configuration refused")).toBeVisible();
  });

  it("names a selected profile field's server refusal without showing unselected values", () => {
    render(
      <SecretFields
        info={PROFILE}
        value={{ fields: { email: "demo@example.test" } }}
        onChange={vi.fn()}
        idPrefix="profile-refused"
        errors={{ "fields.email": "Email refused", fields: "Profile refused" }}
      />,
    );
    expect(screen.getByRole("textbox", { name: "Email" })).toBeInvalid();
    expect(screen.getByText("Email refused")).toBeVisible();
    expect(screen.getByText("Profile refused")).toBeVisible();
  });

  it.each([
    "http://accounts.example",
    "https://accounts.example/login",
    "https://accounts.example?next=x",
    "https://accounts.example#fragment",
    "https://user:pass@accounts.example",
    "https://*.example",
    "https://[invalid",
    "https://accounts.example\\secret",
  ])("refuses a non-origin destination: %s", (origin) => {
    expect(
      isSecretComplete(LOGIN.json_schema, {
        allowed_origins: [origin],
        username: "demo",
        password: "p",
      }),
    ).toBe(false);
  });

  it.each([
    { allowed_origins: null },
    { allowed_origins: [7] },
    { allowed_origins: Array.from({ length: 21 }, () => "https://accounts.example") },
    { username: "" },
    { username: "x".repeat(1025) },
    { password: "" },
    { password: "x".repeat(4097) },
    { totp: { seed: "short", algorithm: "SHA1", digits: 6, period_seconds: 30 } },
    { totp: { seed: "0".repeat(16), algorithm: "SHA1", digits: 6, period_seconds: 30 } },
    { totp: { seed: "A".repeat(209), algorithm: "SHA1", digits: 6, period_seconds: 30 } },
    { totp: { seed: "JBSWY3DPEHPK3PXP", algorithm: "MD5", digits: 6, period_seconds: 30 } },
    { totp: { seed: "JBSWY3DPEHPK3PXP", algorithm: "SHA1", digits: 7, period_seconds: 30 } },
    { totp: { seed: "JBSWY3DPEHPK3PXP", algorithm: "SHA1", digits: 6, period_seconds: 15 } },
  ])("refuses an invalid login shape (%j)", (extra) => {
    expect(
      isSecretComplete(LOGIN.json_schema, {
        allowed_origins: ["https://accounts.example"],
        username: "demo",
        password: "p",
        ...extra,
      }),
    ).toBe(false);
  });

  it.each([null, [], { payment_card: "1234" }, { email: "x".repeat(1025) }])(
    "refuses an invalid profile shape (%j)",
    (fields) => {
      expect(
        isSecretComplete(PROFILE.json_schema, {
          allowed_origins: ["https://contact.example"],
          fields,
        }),
      ).toBe(false);
    },
  );

  it("accepts exact short passwords and complete optional TOTP or contact fields", () => {
    const login = {
      allowed_origins: ["https://accounts.example:8443"],
      username: "demo",
      password: " ",
    };
    expect(isSecretComplete(LOGIN.json_schema, login)).toBe(true);
    expect(
      isSecretComplete(LOGIN.json_schema, {
        ...login,
        totp: { seed: "JBSWY3DPEHPK3PXP", algorithm: "SHA512", digits: 8, period_seconds: 60 },
      }),
    ).toBe(true);
    expect(
      isSecretComplete(PROFILE.json_schema, {
        allowed_origins: ["https://contact.example"],
        fields: { name: "Demo", country: "SG" },
      }),
    ).toBe(true);
  });

  it("offers optional masked TOTP inputs without asking for a JSON object", async () => {
    render(
      <Form
        info={LOGIN}
        initial={{ allowed_origins: ["https://accounts.example"], username: "demo", password: "p" }}
      />,
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Include a verification code (TOTP)" }),
    );
    expect(screen.getByLabelText("Verification code seed")).toHaveAttribute("type", "password");
    expect(screen.getByRole("combobox", { name: "Code algorithm" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Code digits" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Code period" })).toBeVisible();
  });

  it("stores only selected typed contact fields and removes their values when deselected", async () => {
    const changed = vi.fn();
    render(
      <Form
        info={PROFILE}
        initial={{ allowed_origins: ["https://contact.example"], fields: {} }}
        onChange={changed}
      />,
    );
    const email = screen.getByRole("checkbox", { name: "Use email" });
    await userEvent.click(email);
    await userEvent.type(screen.getByRole("textbox", { name: "Email" }), "demo@example.com");
    expect(changed).toHaveBeenLastCalledWith({
      allowed_origins: ["https://contact.example"],
      fields: { email: "demo@example.com" },
    });
    await userEvent.click(email);
    expect(changed).toHaveBeenLastCalledWith({
      allowed_origins: ["https://contact.example"],
      fields: {},
    });
    expect(screen.queryByRole("textbox", { name: "Email" })).not.toBeInTheDocument();
  });

  it.each([
    [LOGIN, { allowed_origins: [], username: "demo", password: "p" }],
    [
      LOGIN,
      { allowed_origins: ["https://accounts.example"], username: "demo", password: "p", totp: {} },
    ],
    [PROFILE, { allowed_origins: ["https://contact.example"], fields: {} }],
    [PROFILE, { allowed_origins: ["https://contact.example"], fields: { email: "" } }],
  ])("refuses an incomplete browser credential before submission (%j)", (info, value) => {
    expect(isSecretComplete(info.json_schema, value)).toBe(false);
  });
});
