import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AddChannelDialog } from "./add-channel-dialog";

vi.mock("@/hooks", () => ({ useOrganizationList: () => ({ data: [] }) }));
vi.mock("@/components/channels/transcription-fields", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/channels/transcription-fields")>()),
  TranscriptionFields: () => null,
}));

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
}

describe("registering a Discord bot (#2079)", () => {
  it("is offered, with where its token comes from", () => {
    render(<AddChannelDialog open onOpenChange={vi.fn()} onSubmit={vi.fn()} isPending={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Discord" }));

    expect(screen.getByRole("button", { name: "Discord" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Message Content Intent/)).toBeInTheDocument();
  });

  it("sends its token alone - it connects over its Gateway and takes no webhook", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <AddChannelDialog
        open
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
        isPending={false}
        initialPlatform="discord"
      />,
    );
    type("Name", "Support");
    type("Bot token", "discord-bot-token");

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const sent = onSubmit.mock.calls[0]?.[0];
    expect(sent).toMatchObject({ platform: "discord", token: "discord-bot-token" });
    expect(sent).not.toHaveProperty("webhook_mode");
    expect(sent).not.toHaveProperty("webhook_secret");
  });
});
