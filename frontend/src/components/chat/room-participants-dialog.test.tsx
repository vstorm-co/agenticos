import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import type { RoomParticipantRead } from "@/types/room";
import type { Conversation } from "@/types/conversation";
import messages from "@/../messages/en.json";
import { RoomParticipantsDialog } from "./room-participants-dialog";

const hooks = vi.hoisted(() => ({
  participants: {
    participants: [] as RoomParticipantRead[],
    visibility: "private" as "private" | "public" | null,
    canPost: true,
    canManage: true,
    isLoading: false,
    error: null as unknown,
    refetch: vi.fn(),
  },
  mentionables: {
    mentionables: [] as RoomParticipantRead[],
    isLoading: false,
    error: null as unknown,
    refetch: vi.fn(),
  },
  add: vi.fn(),
  remove: vi.fn(),
  updateAutoReply: vi.fn(),
  join: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  useRoomParticipants: () => hooks.participants,
  useRoomMentionables: () => hooks.mentionables,
  useAddRoomParticipant: () => ({ add: hooks.add, isAdding: false }),
  useRemoveRoomParticipant: () => ({ remove: hooks.remove, isRemoving: false }),
  useUpdateRoomAgentAutoReply: () => ({ update: hooks.updateAutoReply, isUpdating: false }),
  useJoinPublicRoom: () => ({ join: hooks.join, isJoining: false }),
}));

function participant(
  kind: "user" | "agent",
  id: string,
  name: string,
  isMember: boolean,
  canAdd = false,
): RoomParticipantRead {
  return {
    kind,
    id,
    name,
    avatar_url: null,
    is_member: isMember,
    can_add: canAdd,
    can_mention: isMember || canAdd,
    auto_reply: false,
  };
}

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "conversation-1",
    user_id: "owner-1",
    title: "Launch planning",
    project_id: null,
    room_visibility: "private",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    is_archived: false,
    ...overrides,
  };
}

function drawRoom(current: Conversation = conversation()) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RoomParticipantsDialog
        conversationId={current.id}
        conversation={current}
        open
        onOpenChange={vi.fn()}
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  hooks.participants = {
    participants: [],
    visibility: "private",
    canPost: true,
    canManage: true,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  };
  hooks.mentionables = { mentionables: [], isLoading: false, error: null, refetch: vi.fn() };
  hooks.add.mockReset().mockResolvedValue(undefined);
  hooks.remove.mockReset().mockResolvedValue(undefined);
  hooks.updateAutoReply.mockReset().mockResolvedValue(undefined);
  hooks.join.mockReset().mockResolvedValue(undefined);
  useAuthStore.setState({
    user: { id: "viewer-1", email: "viewer@example.com", is_active: true } as User,
  });
});

describe("RoomParticipantsDialog", () => {
  it("lets a room manager add a person after showing the saved-history notice", async () => {
    const user = userEvent.setup();
    hooks.participants.participants = [
      participant("user", "owner-1", "Owner", true),
      participant("user", "viewer-1", "Current user", true),
      participant("user", "member-2", "Sam", true),
    ];
    hooks.mentionables.mentionables = [participant("user", "new-person", "Morgan", false, true)];
    drawRoom();

    expect(screen.queryByRole("button", { name: "Remove Owner" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Current user" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Sam" })).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: /Morgan/ }));
    expect(screen.getByRole("heading", { name: "Add Morgan to this room?" })).toBeInTheDocument();
    expect(
      screen.getByText("They will be able to read the room’s existing conversation history."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Share history and add" }));

    await waitFor(() => expect(hooks.add).toHaveBeenCalledWith({ kind: "user", id: "new-person" }));
  });

  it("allows a non-manager to add an authorized agent without adding people", async () => {
    const user = userEvent.setup();
    hooks.participants.canManage = false;
    hooks.participants.canPost = true;
    hooks.mentionables.mentionables = [
      participant("user", "person-2", "Morgan", false, false),
      participant("agent", "agent-1", "Launch agent", false, true),
    ];
    drawRoom();

    expect(screen.queryByRole("option", { name: /Morgan/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: /Launch agent/ }));
    expect(
      screen.getByRole("heading", { name: "Add Launch agent to this room?" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Share history and add" }));

    await waitFor(() => expect(hooks.add).toHaveBeenCalledWith({ kind: "agent", id: "agent-1" }));
  });

  it("warns that converting a saved direct chat shares its history before adding", async () => {
    const user = userEvent.setup();
    hooks.participants.visibility = null;
    hooks.mentionables.mentionables = [participant("user", "new-person", "Morgan", false, true)];
    drawRoom(conversation({ room_visibility: null }));

    await user.click(screen.getByRole("option", { name: /Morgan/ }));
    expect(
      screen.getByRole("heading", { name: "Turn this conversation into a private room?" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Adding Morgan gives them access to the full conversation history, including earlier messages.",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Convert and add" }));

    await waitFor(() => expect(hooks.add).toHaveBeenCalledWith({ kind: "user", id: "new-person" }));
  });
});
