import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "@/types/conversation";
import messages from "@/../messages/en.json";
import { RoomDirectoryDialog } from "./room-directory-dialog";

const hooks = vi.hoisted(() => ({
  rooms: [] as Conversation[],
  isLoading: false,
  error: null as unknown,
  refetch: vi.fn(),
  isJoining: false,
  join: vi.fn(),
  create: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  useRoomDirectory: () => ({
    rooms: hooks.rooms,
    total: hooks.rooms.length,
    isLoading: hooks.isLoading,
    error: hooks.error,
    refetch: hooks.refetch,
  }),
  useJoinPublicRoom: () => ({ join: hooks.join, isJoining: hooks.isJoining }),
  useCreateRoomConversation: () => ({ create: hooks.create, isCreating: false }),
}));

function room(
  id: string,
  title: string,
  visibility: "private" | "public" = "public",
): Conversation {
  return {
    id,
    title,
    room_visibility: visibility,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    is_archived: false,
  };
}

function drawDirectory(onSelect = vi.fn(), onCreated = vi.fn()) {
  const onOpenChange = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RoomDirectoryDialog
        open
        onOpenChange={onOpenChange}
        onSelectConversation={onSelect}
        onCreated={onCreated}
      />
    </NextIntlClientProvider>,
  );
  return { onOpenChange, onSelect, onCreated };
}

beforeEach(() => {
  hooks.rooms = [];
  hooks.isLoading = false;
  hooks.error = null;
  hooks.refetch.mockReset();
  hooks.isJoining = false;
  hooks.join.mockReset();
  hooks.create.mockReset();
});

describe("RoomDirectoryDialog", () => {
  it("joins a public room and selects the joined conversation", async () => {
    const user = userEvent.setup();
    const publicRoom = room("public-1", "Release planning");
    const joinedRoom = { ...publicRoom, room_visibility: "public" as const };
    hooks.rooms = [publicRoom];
    hooks.join.mockResolvedValue(joinedRoom);
    const callbacks = drawDirectory();

    await user.click(screen.getByRole("button", { name: "Join" }));

    await waitFor(() => {
      expect(hooks.join).toHaveBeenCalledWith("public-1");
      expect(callbacks.onSelect).toHaveBeenCalledWith(joinedRoom);
      expect(callbacks.onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("creates a public room and opens it through the created callback", async () => {
    const user = userEvent.setup();
    const createdRoom = room("created-1", "Launch planning");
    hooks.create.mockResolvedValue(createdRoom);
    const callbacks = drawDirectory();

    await user.click(screen.getByRole("button", { name: "Create room" }));
    await user.type(screen.getByRole("textbox", { name: "Room name" }), "Launch planning");
    await user.click(screen.getByRole("combobox", { name: "Visibility" }));
    await user.click(await screen.findByRole("option", { name: "Public" }));
    await user.click(screen.getByRole("button", { name: "Create room" }));

    await waitFor(() => {
      expect(hooks.create).toHaveBeenCalledWith({
        title: "Launch planning",
        visibility: "public",
        participants: [],
      });
      expect(callbacks.onCreated).toHaveBeenCalledWith(createdRoom);
      expect(callbacks.onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("does not select a stale join result after a tenant switch", async () => {
    const user = userEvent.setup();
    hooks.rooms = [room("public-1", "Release planning")];
    let resolveJoin!: (value: Conversation | null) => void;
    hooks.join.mockReturnValueOnce(
      new Promise<Conversation | null>((resolve) => {
        resolveJoin = resolve;
      }),
    );
    const callbacks = drawDirectory();

    await user.click(screen.getByRole("button", { name: "Join" }));
    // The scope-aware hook drops a response belonging to the previous tenant.
    await resolveDeferred(() => resolveJoin(null));

    expect(callbacks.onSelect).not.toHaveBeenCalled();
    expect(callbacks.onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("does not open a room created by a request dropped after a tenant switch", async () => {
    const user = userEvent.setup();
    let resolveCreate!: (value: Conversation | null) => void;
    hooks.create.mockReturnValueOnce(
      new Promise<Conversation | null>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const callbacks = drawDirectory();

    await user.click(screen.getByRole("button", { name: "Create room" }));
    await user.type(screen.getByRole("textbox", { name: "Room name" }), "Private planning");
    await user.click(screen.getByRole("button", { name: "Create room" }));
    await resolveDeferred(() => resolveCreate(null));

    expect(callbacks.onCreated).not.toHaveBeenCalled();
    expect(callbacks.onOpenChange).not.toHaveBeenCalledWith(false);
  });
});

async function resolveDeferred(resolve: () => void): Promise<void> {
  await act(async () => {
    resolve();
    await Promise.resolve();
  });
}
