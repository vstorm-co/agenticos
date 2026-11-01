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
      initialPlatform="email"
    />,
  );
  return onSubmit;
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
}

describe("registering an e-mail bot (#2082)", () => {
  it("cannot be registered without the secret the relay signs with", () => {
    open();
    type("Name", "Inbox");
    type("Bot token", "agent@mail.example.com");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("generates a secret and sends the bot as webhook-only", async () => {
    const onSubmit = open();
    type("Name", "Inbox");
    type("Bot token", "agent@mail.example.com");

    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const sent = onSubmit.mock.calls[0]?.[0];
    expect(sent).toMatchObject({
      platform: "email",
      token: "agent@mail.example.com",
      webhook_mode: true,
    });
    expect(sent.webhook_secret).toMatch(/^[0-9a-f]{48}$/);
  });
});
