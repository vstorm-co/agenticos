import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/../messages/en.json";
import { RoomParticipantsButton } from "./room-participants-button";

vi.mock("@/hooks", () => ({
  useRoomParticipants: () => ({
    participants: [],
    visibility: "private",
    canPost: true,
    canManage: true,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useRoomMentionables: () => ({ mentionables: [], isLoading: false, error: null, refetch: vi.fn() }),
  useAddRoomParticipant: () => ({ add: vi.fn(), isAdding: false }),
  useRemoveRoomParticipant: () => ({ remove: vi.fn(), isRemoving: false }),
  useUpdateRoomAgentAutoReply: () => ({ update: vi.fn(), isUpdating: false }),
  useJoinPublicRoom: () => ({ join: vi.fn(), isJoining: false }),
}));

function drawButton(showLabel?: boolean) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RoomParticipantsButton
        conversationId="conversation-1"
        conversation={null}
        showLabel={showLabel}
      />
    </NextIntlClientProvider>,
  );
}

describe("RoomParticipantsButton", () => {
  it("opens the roster dialog and closes it again", async () => {
    const user = userEvent.setup();
    drawButton();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Participants" }));
    expect(screen.getByRole("dialog", { name: "Room participants" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("omits the visible label when asked to", () => {
    const view = drawButton(false);

    expect(screen.getByRole("button", { name: "Participants" })).toBeInTheDocument();
    expect(view.container.querySelector(".sr-only")).toBeNull();
  });
});
