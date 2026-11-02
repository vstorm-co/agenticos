import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AddChannelDialog } from "./add-channel-dialog";

vi.mock("@/hooks", () => ({ useOrganizationList: () => ({ data: [] }) }));
vi.mock("@/components/channels/transcription-fields", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/channels/transcription-fields")>()),
  TranscriptionFields: () => null,
}));

function open(onSubmit = vi.fn().mockResolvedValue(undefined)) {
  render(
    <AddChannelDialog
      open
      onOpenChange={vi.fn()}
      onSubmit={onSubmit}
      isPending={false}
      initialPlatform="whatsapp"
    />,
  );
  return onSubmit;
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
}

const FIELDS: Record<string, string> = {
  Name: "Support",
  "Bot token": "system-user-access-token",
  "Phone number ID": "106540352242922",
  "WhatsApp Business account ID": "102290129340398",
  "App secret": "meta-app-secret-value",
  "Verify token": "my-verify-token",
};

function fill(except?: string) {
  for (const [label, value] of Object.entries(FIELDS)) {
    if (label !== except) type(label, value);
  }
}

describe("registering a WhatsApp bot (#2076)", () => {
  it("creates a whatsapp bot with its five fields", async () => {
    const onSubmit = open();
    fill();

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({
      platform: "whatsapp",
      token: "system-user-access-token",
      whatsapp_phone_number_id: "106540352242922",
      whatsapp_account_id: "102290129340398",
      webhook_secret: "meta-app-secret-value",
      whatsapp_verify_token: "my-verify-token",
    });
    // Always a webhook bot: the backend sets it, so the form does not ask.
    expect(onSubmit.mock.calls[0]?.[0]).not.toHaveProperty("webhook_mode");
  });

  it.each(Object.keys(FIELDS).filter((label) => label !== "Name"))(
    "requires every whatsapp field: %s",
    (missing) => {
      open();
      fill(missing);

      expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
    },
  );

  it("refuses ids that are not digits and secrets that are too short", () => {
    open();
    fill();
    type("Phone number ID", "not-a-number");
    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();

    type("Phone number ID", FIELDS["Phone number ID"]!);
    type("Verify token", "short");
    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("offers no group mentions switch: every WhatsApp chat is private", () => {
    open();

    expect(screen.queryByRole("switch", { name: "Respond to group mentions" })).toBeNull();
  });

  it("keeps its secrets in password inputs", () => {
    open();
    for (const label of ["Bot token", "App secret", "Verify token"]) {
      expect(screen.getByLabelText(label, { exact: false })).toHaveAttribute("type", "password");
    }
  });
});
