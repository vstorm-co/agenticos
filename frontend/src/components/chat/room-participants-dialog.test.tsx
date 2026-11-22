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
  flags: { isAdding: false, isRemoving: false, isUpdating: false, isJoining: false },
}));

vi.mock("@/hooks", () => ({
  useRoomParticipants: () => hooks.participants,
  useRoomMentionables: () => hooks.mentionables,
  useAddRoomParticipant: () => ({ add: hooks.add, isAdding: hooks.flags.isAdding }),
  useRemoveRoomParticipant: () => ({ remove: hooks.remove, isRemoving: hooks.flags.isRemoving }),
  useUpdateRoomAgentAutoReply: () => ({
    update: hooks.updateAutoReply,
    isUpdating: hooks.flags.isUpdating,
  }),
  useJoinPublicRoom: () => ({ join: hooks.join, isJoining: hooks.flags.isJoining }),
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

function roomTree(current: Conversation | null) {
  return (
    <NextIntlClientProvider locale="en" messages={messages}>
      <RoomParticipantsDialog
        conversationId="conversation-1"
        conversation={current}
        open
        onOpenChange={vi.fn()}
      />
    </NextIntlClientProvider>
  );
}

function drawRoom(current: Conversation | null = conversation()) {
  const view = render(roomTree(current));
  return { ...view, redraw: () => view.rerender(roomTree(current)) };
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
  hooks.flags = { isAdding: false, isRemoving: false, isUpdating: false, isJoining: false };
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

  it("removes a member after confirmation and closes the prompt", async () => {
    const user = userEvent.setup();
    hooks.participants.participants = [participant("user", "member-2", "Sam", true)];
    drawRoom();

    await user.click(screen.getByRole("button", { name: "Remove Sam" }));
    expect(screen.getByRole("heading", { name: "Remove Sam?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(hooks.remove).toHaveBeenCalledWith({ kind: "user", id: "member-2" }));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Remove Sam?" })).not.toBeInTheDocument(),
    );
  });

  it("keeps the prompt open with a removal error, and cancel clears it", async () => {
    const user = userEvent.setup();
    hooks.participants.participants = [participant("user", "member-2", "Sam", true)];
    hooks.remove.mockRejectedValue("refused");
    drawRoom();

    await user.click(screen.getByRole("button", { name: "Remove Sam" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("Participant could not be removed.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("heading", { name: "Remove Sam?" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove Sam" }));
    expect(screen.queryByText("Participant could not be removed.")).not.toBeInTheDocument();
  });

  it("shows the add error and the thrown message when an add is refused", async () => {
    const user = userEvent.setup();
    hooks.mentionables.mentionables = [participant("user", "new-person", "Morgan", false, true)];
    hooks.add.mockRejectedValueOnce("refused").mockRejectedValueOnce(new Error("Room is full"));
    drawRoom();

    await user.click(screen.getByRole("option", { name: /Morgan/ }));
    await user.click(screen.getByRole("button", { name: "Share history and add" }));
    expect(await screen.findByText("Participant could not be added.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Share history and add" }));
    expect(await screen.findByText("Room is full")).toBeInTheDocument();
  });

  it("locks the confirmation while a write is pending", async () => {
    const user = userEvent.setup();
    hooks.participants.participants = [participant("user", "member-2", "Sam", true)];
    const view = drawRoom();

    await user.click(screen.getByRole("button", { name: "Remove Sam" }));
    hooks.flags.isRemoving = true;
    view.redraw();

    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("heading", { name: "Remove Sam?" })).toBeInTheDocument();
  });

  it("toggles automatic replies for an agent and reports a failed save", async () => {
    const user = userEvent.setup();
    hooks.participants.participants = [participant("agent", "agent-1", "Launch agent", true)];
    hooks.updateAutoReply.mockRejectedValueOnce("refused");
    drawRoom();

    const toggle = screen.getByRole("switch", {
      name: "Allow automatic replies from Launch agent",
    });
    await user.click(toggle);
    expect(await screen.findByText("Automatic reply setting could not be saved.")).toBeVisible();
    await user.click(toggle);
    await waitFor(() => expect(hooks.updateAutoReply).toHaveBeenLastCalledWith("agent-1", true));
    await waitFor(() =>
      expect(screen.queryByText("Automatic reply setting could not be saved.")).toBeNull(),
    );
  });

  it("lets a non-poster join a public room and refetches the roster", async () => {
    const user = userEvent.setup();
    hooks.participants.visibility = "public";
    hooks.participants.canPost = false;
    drawRoom(conversation({ room_visibility: "public", project_id: undefined }));

    expect(screen.getByText("Only a room manager can change participants.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Join" }));

    await waitFor(() => expect(hooks.join).toHaveBeenCalledWith("conversation-1"));
    await waitFor(() => expect(hooks.participants.refetch).toHaveBeenCalled());
  });

  it("reports a failed join and shows the joining state", async () => {
    const user = userEvent.setup();
    hooks.participants.visibility = "public";
    hooks.participants.canPost = false;
    hooks.join.mockRejectedValue("refused");
    const view = drawRoom(conversation({ room_visibility: "public" }));

    await user.click(screen.getByRole("button", { name: "Join" }));
    expect(await screen.findByText("Room could not be joined.")).toBeVisible();

    hooks.flags.isJoining = true;
    view.redraw();
    expect(screen.getByRole("button", { name: "Joining…" })).toBeDisabled();
  });

  it("does not offer to join an archived public room", () => {
    hooks.participants.visibility = "public";
    hooks.participants.canPost = false;
    drawRoom(conversation({ room_visibility: "public", is_archived: true }));

    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("offers only agents in a project conversation and hides person removal", () => {
    hooks.participants.participants = [
      participant("user", "member-2", "Sam", true),
      participant("agent", "agent-2", "Helper", true),
    ];
    hooks.mentionables.mentionables = [
      participant("user", "person-2", "Morgan", false, true),
      participant("agent", "agent-1", "Launch agent", false, true),
    ];
    drawRoom(conversation({ project_id: "project-1" }));

    expect(screen.queryByRole("option", { name: /Morgan/ })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Launch agent/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Sam" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Helper" })).toBeInTheDocument();
  });

  it("renders with no conversation loaded", () => {
    drawRoom(null);

    expect(screen.getByText("No participants are listed.")).toBeVisible();
  });

  it("retries a failed roster load", async () => {
    const user = userEvent.setup();
    hooks.participants.error = new Error("down");
    drawRoom();

    expect(screen.getByText("Participants could not be loaded.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(hooks.participants.refetch).toHaveBeenCalled();
  });

  it("shows the roster loading state", () => {
    hooks.participants.isLoading = true;
    drawRoom();

    expect(screen.getByRole("status")).toHaveTextContent("Loading participants…");
  });

  it("shows the candidate loading state and retries a failed candidate load", async () => {
    const user = userEvent.setup();
    hooks.mentionables.isLoading = true;
    const view = drawRoom();
    expect(screen.getByRole("status")).toHaveTextContent("Loading participants…");

    hooks.mentionables.isLoading = false;
    hooks.mentionables.error = new Error("down");
    view.redraw();
    expect(screen.getByText("People and agents could not be loaded.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(hooks.mentionables.refetch).toHaveBeenCalled();
  });
});
