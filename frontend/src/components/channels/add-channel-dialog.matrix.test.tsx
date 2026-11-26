import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

function renderMatrix(onSubmit = vi.fn().mockResolvedValue(undefined)) {
  render(
    <AddChannelDialog
      open
      onOpenChange={vi.fn()}
      onSubmit={onSubmit}
      isPending={false}
      initialPlatform="matrix"
    />,
  );
  return onSubmit;
}

describe("registering a Matrix bot", () => {
  it("is offered, with where its token comes from", () => {
    render(<AddChannelDialog open onOpenChange={vi.fn()} onSubmit={vi.fn()} isPending={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Matrix" }));

    expect(screen.getByRole("button", { name: "Matrix" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/issue-compatibility-token/)).toBeInTheDocument();
  });

  it("requires the homeserver, since a self-hosted bot cannot reply without it", () => {
    renderMatrix();
    type("Name", "Support");
    type("Bot token", "syt_matrix_access_token");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
    type("Homeserver URL", "https://matrix.example.org");
    expect(screen.getByRole("button", { name: "Register" })).toBeEnabled();
  });

  it("sends its token and homeserver alone - it streams its sync and takes no webhook", async () => {
    const onSubmit = renderMatrix();
    type("Name", "Support");
    type("Bot token", "syt_matrix_access_token");
    type("Homeserver URL", " https://matrix.example.org ");

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const sent = onSubmit.mock.calls[0]?.[0];
    expect(sent).toMatchObject({
      platform: "matrix",
      token: "syt_matrix_access_token",
      api_base_url: "https://matrix.example.org",
      ack_reaction: "eyes",
    });
    expect(sent).not.toHaveProperty("webhook_mode");
    expect(sent).not.toHaveProperty("webhook_secret");
    expect(sent).not.toHaveProperty("command_token");
    expect(sent).not.toHaveProperty("access_policy.discord_guild_ids");
  });

  it("offers a reaction on the question, as Slack and Mattermost do", async () => {
    renderMatrix();

    await userEvent.click(screen.getByRole("button", { name: "More options" }));

    expect(screen.getByRole("combobox", { name: "React to a question with" })).toBeInTheDocument();
  });

  it("does not carry a Matrix homeserver over to another platform", async () => {
    const onSubmit = renderMatrix();
    type("Homeserver URL", "https://matrix.example.org");

    await userEvent.click(screen.getByRole("button", { name: "Telegram" }));
    type("Name", "Support");
    type("Bot token", "telegram-bot-token");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(onSubmit.mock.calls[0]?.[0]).not.toHaveProperty("api_base_url");
  });
});
