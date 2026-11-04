import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AddChannelDialog } from "./add-channel-dialog";

vi.mock("@/hooks", () => ({ useOrganizationList: () => ({ data: [] }) }));
vi.mock("@/components/channels/transcription-fields", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/channels/transcription-fields")>()),
  TranscriptionFields: () => null,
}));

const APP_ID = "11111111-1111-1111-1111-111111111111";
const TENANT = "22222222-2222-2222-2222-222222222222";

function open(onSubmit = vi.fn().mockResolvedValue(undefined)) {
  render(
    <AddChannelDialog
      open
      onOpenChange={vi.fn()}
      onSubmit={onSubmit}
      isPending={false}
      initialPlatform="teams"
    />,
  );
  return onSubmit;
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
}

describe("registering a Teams bot (#1985)", () => {
  it("cannot be registered without its app and tenant", () => {
    open();
    type("Name", "Support");
    type("Bot token", "client-secret-value");
    type("Microsoft App ID", APP_ID);
    type("Tenant ID", "not-a-guid");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("sends its registration beside the client secret", async () => {
    const onSubmit = open();
    type("Name", "Support");
    type("Bot token", "client-secret-value");
    type("Microsoft App ID", APP_ID);
    type("Tenant ID", TENANT);

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({
      platform: "teams",
      token: "client-secret-value",
      teams_app_id: APP_ID,
      teams_tenant_id: TENANT,
    });
  });
});
