import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AddChannelDialog } from "./add-channel-dialog";

vi.mock("@/hooks", () => ({ useOrganizationList: () => ({ data: [] }) }));
vi.mock("@/components/channels/transcription-fields", async (original) => ({
  ...(await original<typeof import("@/components/channels/transcription-fields")>()),
  TranscriptionFields: () => null,
}));

describe("registering the company iMessage bridge", () => {
  it("requires the bridge endpoint and sends a webhook bot without inventing a callback secret", async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(
      <AddChannelDialog
        open
        onOpenChange={vi.fn()}
        onSubmit={submit}
        isPending={false}
        initialPlatform="imessage"
      />,
    );
    fireEvent.change(screen.getByLabelText("Name", { exact: false }), {
      target: { value: "Company Mac" },
    });
    fireEvent.change(screen.getByLabelText("Bot token", { exact: false }), {
      target: { value: "bridge-password" },
    });
    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("BlueBubbles server URL", { exact: false }), {
      target: { value: "http://company-mac:1234" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0]?.[0]).toMatchObject({
      platform: "imessage",
      webhook_mode: true,
      api_base_url: "http://company-mac:1234",
      token: "bridge-password",
    });
    expect(submit.mock.calls[0]?.[0]).not.toHaveProperty("webhook_secret");
  });
});
