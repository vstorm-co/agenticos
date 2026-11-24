import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/../messages/en.json";
import type { RoomParticipantRead } from "@/types/room";
import { RoomParticipantRow } from "./room-participant-row";

function member(overrides: Partial<RoomParticipantRead> = {}): RoomParticipantRead {
  return {
    kind: "agent",
    id: "agent-1",
    name: "Launch agent",
    avatar_url: null,
    is_member: true,
    can_add: false,
    can_mention: true,
    auto_reply: true,
    ...overrides,
  };
}

function drawRow(
  participant: RoomParticipantRead,
  props: Partial<Parameters<typeof RoomParticipantRow>[0]> = {},
) {
  const onRemove = vi.fn();
  const onAutoReplyChange = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ul>
        <RoomParticipantRow
          participant={participant}
          currentUserId="viewer-1"
          canManage
          canRemove
          isUpdatingAutoReply={false}
          isRemoving={false}
          onRemove={onRemove}
          onAutoReplyChange={onAutoReplyChange}
          {...props}
        />
      </ul>
    </NextIntlClientProvider>,
  );
  return { onRemove, onAutoReplyChange };
}

describe("RoomParticipantRow", () => {
  it("reports a removal and an auto-reply change for the member it shows", async () => {
    const user = userEvent.setup();
    const participant = member();
    const { onRemove, onAutoReplyChange } = drawRow(participant);

    await user.click(screen.getByRole("button", { name: "Remove Launch agent" }));
    expect(onRemove).toHaveBeenCalledWith(participant);
    await user.click(
      screen.getByRole("switch", { name: "Allow automatic replies from Launch agent" }),
    );
    expect(onAutoReplyChange).toHaveBeenCalledWith("agent-1", false);
  });

  it("treats a missing auto-reply flag as off", () => {
    drawRow(member({ auto_reply: undefined }));

    expect(
      screen.getByRole("switch", { name: "Allow automatic replies from Launch agent" }),
    ).not.toBeChecked();
  });

  it("disables the controls while a write is pending", () => {
    drawRow(member(), { isRemoving: true, isUpdatingAutoReply: true });

    expect(screen.getByRole("button", { name: "Remove Launch agent" })).toBeDisabled();
    expect(
      screen.getByRole("switch", { name: "Allow automatic replies from Launch agent" }),
    ).toBeDisabled();
  });

  it("marks the current user and offers them no removal", () => {
    drawRow(member({ kind: "user", id: "viewer-1", name: "Me" }));

    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Me" })).not.toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("shows another person without automatic-reply or removal controls when not managing", () => {
    drawRow(member({ kind: "user", id: "member-2", name: "Sam" }), {
      canManage: false,
      canRemove: false,
    });

    expect(screen.getByText("People")).toBeInTheDocument();
    expect(screen.queryByText("You")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
